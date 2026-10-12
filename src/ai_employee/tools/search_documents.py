"""search_documents: retrieval over the tenant's knowledge base."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ai_employee.context import TurnContext
from ai_employee.db.models import SideEffectClass
from ai_employee.knowledge.retrieval import DEFAULT_TOP_K, MAX_TOP_K, search
from ai_employee.tools.registry import ToolDeclaration, register


class SearchDocumentsInput(BaseModel):
    query: str = Field(min_length=1, description="Standalone search query; resolve pronouns.")
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)


def _handle(
    ctx: TurnContext, args: SearchDocumentsInput, _credential: None
) -> list[dict[str, Any]]:
    return [hit.as_dict() for hit in search(ctx, args.query, args.top_k)]


SEARCH_DOCUMENTS = register(
    ToolDeclaration(
        name="search_documents",
        description=(
            "Search the organisation's documents. Returns passages with source, page and "
            "score. Search again with a refined query if the results do not answer the question."
        ),
        input_model=SearchDocumentsInput,
        side_effect_class=SideEffectClass.READ,
        handler=_handle,
    )
)
