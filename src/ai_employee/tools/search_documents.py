"""The search_documents tool exposed to the agent."""

from __future__ import annotations

import logging

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ai_employee.retrieval import DEFAULT_TOP_K, MAX_TOP_K, search

logger = logging.getLogger(__name__)

# Module level rather than a docstring: the decorator passes a docstring through verbatim,
# and its continuation indentation would be sent to the model on every request.
DESCRIPTION = """\
Searches indexed company documents (policies, wikis, reports, internal docs) using semantic \
vector search. Use this whenever the user asks about company-specific information, policies, \
procedures, or content that would exist in internal documentation.

Returns matching passages, each with its source document name, page number where available, a \
relevance score between 0 and 1, and a chunk id. Cite the source of every passage you use.

An empty result list means nothing relevant is indexed - say so rather than answering from \
general knowledge. Low scores across all results mean the same thing.

Does NOT search databases, live web content, email, or external systems - only pre-indexed \
documents."""


class SearchDocumentsInput(BaseModel):
    query: str = Field(
        description=(
            "A natural language search query. Should be a focused restatement of what "
            "information is needed, not the user's raw message verbatim. E.g. for "
            "\"what's our policy on remote work stipends\", use \"remote work stipend "
            'policy" rather than the full question.'
        )
    )
    top_k: int = Field(
        default=DEFAULT_TOP_K,
        ge=1,
        le=MAX_TOP_K,
        description=(
            "Number of top matching passages to retrieve. Increase for broad or "
            "exploratory questions, keep the default for specific lookups."
        ),
    )


@tool("search_documents", args_schema=SearchDocumentsInput, description=DESCRIPTION)
def search_documents(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Semantic search over indexed documents. See DESCRIPTION for the agent-facing contract."""
    try:
        hits = search(query, top_k=top_k)
    except Exception:
        # Surfaced to the agent as data: a tool exception would abort the graph run,
        # whereas an error payload lets the agent report the failure to the user.
        logger.exception("search_documents failed for query %r", query)
        return {
            "results": [],
            "count": 0,
            "error": "Document search is unavailable. Report this rather than guessing an answer.",
        }

    return {"results": [hit.as_dict() for hit in hits], "count": len(hits)}