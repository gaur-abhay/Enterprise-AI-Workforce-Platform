"""FastAPI application exposing the agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ai_employee import llm
from ai_employee.agent import AgentNotConfiguredError, ask
from ai_employee.config import get_settings
from ai_employee.db import connect

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI Employee",
    version="0.1.0",
    description="Agentic RAG over indexed company documents.",
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(
        default=None,
        description="Omit to start a new conversation; pass the returned value to continue one.",
    )


class Source(BaseModel):
    chunk_id: str
    source: str | None = None
    page: int | None = None
    score: float | None = None


class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    # Passages the model was shown, not necessarily the ones it cited.
    sources: list[Source] = []
    tool_calls: list[dict[str, Any]] = []


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse | JSONResponse:
    """Run one conversational turn.

    Declared sync on purpose: ask() blocks on the model, the database, and Ollama, so
    FastAPI runs it in a worker thread instead of stalling the event loop.
    """
    thread_id = request.thread_id or str(uuid.uuid4())

    try:
        result = ask(request.message, thread_id=thread_id)
    except AgentNotConfiguredError as exc:
        logger.error("agent not configured: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    except Exception:
        logger.exception("chat turn failed for thread %s", thread_id)
        return JSONResponse(status_code=500, content={"detail": "The agent failed to answer."})

    return ChatResponse(
        answer=result.answer,
        thread_id=thread_id,
        sources=[Source(**source) for source in result.sources],
        tool_calls=result.tool_calls,
    )


def _check_database() -> tuple[bool, str]:
    try:
        with connect(register_types=False) as conn:
            conn.execute("SELECT 1")
        return True, "ok"
    except Exception as exc:
        return False, type(exc).__name__


def _check_embeddings() -> tuple[bool, str]:
    """Only Ollama is checked over the wire; a hosted provider is validated by its key."""
    settings = get_settings()
    if settings.embedding_provider != "ollama":
        if settings.embedding_provider == "gemini" and not settings.google_api_key:
            return False, "gemini: missing GOOGLE_API_KEY"
        return True, f"{settings.embedding_provider}: {settings.gemini_embedding_model}"

    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        response.raise_for_status()
    except Exception as exc:
        return False, f"ollama: {type(exc).__name__}"

    models = {model.get("name", "").split(":")[0] for model in response.json().get("models", [])}
    if settings.embedding_model not in models:
        return False, f"ollama: {settings.embedding_model} not pulled"
    return True, f"ollama: {settings.embedding_model}"


@app.get("/health")
def health() -> JSONResponse:
    """Reports each dependency separately, so a failure says which one is down."""
    checks = {
        "database": _check_database(),
        "embeddings": _check_embeddings(),
        "llm": llm.check_config(),
    }
    healthy = all(ok for ok, _ in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": {name: detail for name, (_, detail) in checks.items()},
        },
    )