"""Tool declarations. A tool is what the dispatcher enforces, not just a function."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from ai_employee.context import TurnContext
from ai_employee.db.models import SideEffectClass

# (context, validated input, credential or None) -> JSON-serialisable result.
Handler = Callable[[TurnContext, Any, Any], Any]


@dataclass(frozen=True)
class ToolDeclaration:
    name: str
    description: str
    input_model: type[BaseModel]
    side_effect_class: SideEffectClass
    handler: Handler
    # Per-user connection the tool needs a credential from; None for none.
    connection_type: str | None = None

    def spec(self) -> dict[str, Any]:
        """Provider-neutral function spec for binding to a model."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        }


_REGISTRY: dict[str, ToolDeclaration] = {}


def register(declaration: ToolDeclaration) -> ToolDeclaration:
    if declaration.name in _REGISTRY:
        raise ValueError(f"tool {declaration.name!r} is already registered")
    _REGISTRY[declaration.name] = declaration
    return declaration


def get(name: str) -> ToolDeclaration | None:
    return _REGISTRY.get(name)


def available(ctx: TurnContext) -> list[ToolDeclaration]:
    """Tools offered to the model for this turn. Per-tenant grants filter here later."""
    return list(_REGISTRY.values())
