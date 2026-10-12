"""Agent tools. ALL_TOOLS is what gets bound to the model."""

from ai_employee.tools.search_documents import search_documents

ALL_TOOLS = [search_documents]

__all__ = ["ALL_TOOLS", "search_documents"]
