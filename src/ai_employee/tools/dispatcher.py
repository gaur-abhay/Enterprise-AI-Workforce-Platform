"""The only path from the model to a tool: validate, policy, credentials, execute, audit."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ai_employee.context import TurnContext
from ai_employee.db import tenant_session
from ai_employee.db.models import SideEffectClass, ToolCall, ToolOutcome
from ai_employee.tools import registry
from ai_employee.tools.registry import ToolDeclaration

logger = logging.getLogger(__name__)

# Stands in for the tenant policy table.
WRITE_REQUIRES_APPROVAL = True


@dataclass(frozen=True)
class Ok:
    value: Any


@dataclass(frozen=True)
class Error:
    # Shown to the model, so it can correct the call or tell the user.
    message: str


@dataclass(frozen=True)
class PendingApproval:
    tool_name: str
    arguments: dict[str, Any]


Result = Ok | Error | PendingApproval


class CredentialUnavailableError(RuntimeError):
    pass


def requires_approval(declaration: ToolDeclaration) -> bool:
    """Irreversible always requires approval; no policy can lower that floor."""
    match declaration.side_effect_class:
        case SideEffectClass.READ:
            return False
        case SideEffectClass.IRREVERSIBLE:
            return True
        case SideEffectClass.WRITE:
            return WRITE_REQUIRES_APPROVAL


def resolve_credential(ctx: TurnContext, declaration: ToolDeclaration) -> Any:
    """The model never sees what this returns."""
    if declaration.connection_type is None:
        return None
    raise CredentialUnavailableError(f"no {declaration.connection_type} connection available")


def _audit(
    ctx: TurnContext,
    name: str,
    declaration: ToolDeclaration | None,
    arguments: dict[str, Any],
    result: Result,
    started: float,
) -> None:
    outcome = {
        Ok: ToolOutcome.OK,
        Error: ToolOutcome.ERROR,
        PendingApproval: ToolOutcome.PENDING_APPROVAL,
    }[type(result)]
    with tenant_session(ctx.tenant_id) as session:
        session.add(
            ToolCall(
                tenant_id=ctx.tenant_id,
                correlation_id=ctx.correlation_id,
                employee_id=ctx.employee_id,
                actor=str(ctx.actor),
                tool_name=name,
                side_effect_class=declaration.side_effect_class if declaration else None,
                arguments=arguments,
                outcome=outcome,
                error=result.message if isinstance(result, Error) else None,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        )


def _run(ctx: TurnContext, declaration: ToolDeclaration, arguments: dict[str, Any]) -> Result:
    try:
        validated = declaration.input_model.model_validate(arguments)
    except ValidationError as exc:
        return Error(f"invalid arguments for {declaration.name}: {exc.errors(include_url=False)}")

    if requires_approval(declaration):
        return PendingApproval(tool_name=declaration.name, arguments=arguments)

    try:
        credential = resolve_credential(ctx, declaration)
        return Ok(declaration.handler(ctx, validated, credential))
    except CredentialUnavailableError as exc:
        return Error(str(exc))
    except Exception:
        logger.exception("tool %s failed", declaration.name)
        return Error(f"{declaration.name} failed unexpectedly; try again or answer without it")


def dispatch(ctx: TurnContext, name: str, arguments: dict[str, Any]) -> Result:
    """Run one tool call and record it, whatever the outcome."""
    started = time.monotonic()
    declaration = registry.get(name)
    result = _run(ctx, declaration, arguments) if declaration else Error(f"unknown tool {name!r}")
    _audit(ctx, name, declaration, arguments, result, started)
    return result
