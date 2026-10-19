"""send_email: a write tool. Held for the requester's confirmation before it runs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field

from ai_employee.context import TurnContext
from ai_employee.db import tenant_session
from ai_employee.db.models import OutboxMessage, SideEffectClass
from ai_employee.tools.registry import ToolDeclaration, register


class SendEmailInput(BaseModel):
    to: EmailStr
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000)


def _handle(ctx: TurnContext, args: SendEmailInput, _credential: None) -> dict[str, Any]:
    # Recorded in the outbox; real delivery arrives with the per-user mail connection.
    message = OutboxMessage(
        tenant_id=ctx.tenant_id,
        recipient=str(args.to),
        subject=args.subject,
        body=args.body,
        sent_by=str(ctx.actor),
        correlation_id=ctx.correlation_id,
    )
    with tenant_session(ctx.tenant_id) as session:
        session.add(message)
        session.flush()
        return {"status": "sent", "message_id": str(message.id), "to": str(args.to)}


SEND_EMAIL = register(
    ToolDeclaration(
        name="send_email",
        description=(
            "Send an email on the user's behalf. The user is shown the exact message and must "
            "confirm before it is sent; draft it completely."
        ),
        input_model=SendEmailInput,
        side_effect_class=SideEffectClass.WRITE,
        handler=_handle,
    )
)
