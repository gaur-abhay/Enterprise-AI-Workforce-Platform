"""Agent tools. Importing this package registers every tool."""

from ai_employee.tools import dispatcher, registry, search_documents
from ai_employee.tools.dispatcher import Error, Ok, PendingApproval, Result, dispatch

__all__ = [
    "Error",
    "Ok",
    "PendingApproval",
    "Result",
    "dispatch",
    "dispatcher",
    "registry",
    "search_documents",
]
