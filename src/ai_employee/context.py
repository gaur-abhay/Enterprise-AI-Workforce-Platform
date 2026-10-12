"""TurnContext: the envelope every entry point normalises into before reaching the agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

Trigger = Literal["mention", "schedule", "event", "api"]
SYSTEM_ACTOR = "system"


@dataclass(frozen=True, slots=True)
class TurnContext:
    tenant_id: UUID
    employee_id: UUID
    # User id of the caller, or SYSTEM_ACTOR for scheduled runs.
    actor: UUID | Literal["system"]
    trigger: Trigger
    correlation_id: str
    # Group principals of the actor, matched against acl_principals at retrieval time.
    actor_principals: tuple[str, ...] = ()
    # Channel-specific reply address; opaque to everything except the channel adapter.
    conversation_ref: Mapping[str, Any] | None = field(default=None)
