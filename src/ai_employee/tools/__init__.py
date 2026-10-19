"""Agent tools. Importing this package registers every tool."""

from ai_employee.tools import dispatcher, registry, search_documents, send_email
from ai_employee.tools.dispatcher import (
    Decision,
    Error,
    Ok,
    PendingApproval,
    Result,
    dispatch,
    needs_approval,
)

__all__ = [
    "Decision",
    "Error",
    "Ok",
    "PendingApproval",
    "Result",
    "dispatch",
    "dispatcher",
    "needs_approval",
    "registry",
    "search_documents",
    "send_email",
]
