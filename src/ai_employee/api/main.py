"""FastAPI application exposing the agent."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ai_employee import llm
from ai_employee.agent import AgentNotConfiguredError, ask
from ai_employee.config import get_settings
from ai_employee.db import connect
from ai_employee.observability import configure_logging, current_request_id, request_context

# Before the app exists, so anything logged during import is handled. Uvicorn configures
# only its own loggers, so without this the whole application logs into a void.
configure_logging()

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"

app = FastAPI(
    title="AI Employee",
    version="0.1.0",
    description="Agentic RAG over indexed company documents.",
)


@app.middleware("http")
async def correlate_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Bind one id per request and return it on the response.

    A caller that already has a trace id can pass it in the header and see its own id in
    these logs; anything else gets a fresh one. The id is echoed back so a user reporting a
    bad answer can name the exact turn.
    """
    with request_context(request.headers.get(REQUEST_ID_HEADER)) as request_id:
        started = time.perf_counter()
        response = await call_next(request)
        # DEBUG because uvicorn already writes an access line; this one exists to tie the id
        # to the path when the access log alone is not enough.
        logger.debug(
            "%s %s -> %d in %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - started,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(
        default=None,
        description="Omit to start a new conversation; pass the returned value to continue one.",
    )


class Source(BaseModel):
    """A retrieved passage, in enough detail for a client to render and verify a citation."""

    chunk_id: str
    document_id: str | None = None
    # What the answer cites.
    source: str | None = Field(default=None, description="File name of the source document")
    title: str | None = None
    # Where it actually lives: a path, or azure://account/container/blob.
    uri: str | None = None
    page: int | None = None
    chunk_index: int | None = None
    indexed_at: str | None = Field(
        default=None, description="When the document was last indexed (ISO-8601)"
    )
    score: float | None = None
    # The passage itself, so a client can show what a claim was based on without a second
    # round trip.
    content: str | None = None


class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    # Echoes the correlation id in the logs for this turn, so a reported answer can be found.
    request_id: str | None = None
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
    request_id = current_request_id()

    try:
        result = ask(request.message, thread_id=thread_id)
    except AgentNotConfiguredError as exc:
        logger.error("agent not configured: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc), "request_id": request_id})
    except Exception:
        logger.exception("chat turn failed for thread %s", thread_id)
        return JSONResponse(
            status_code=500,
            content={"detail": "The agent failed to answer.", "request_id": request_id},
        )

    return ChatResponse(
        answer=result.answer,
        thread_id=thread_id,
        request_id=request_id,
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
