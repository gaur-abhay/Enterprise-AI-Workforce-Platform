"""FastAPI application: REST, the chat page, and health."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from ai_employee import llm
from ai_employee.api.routers import approvals, turns
from ai_employee.config import get_settings
from ai_employee.db import get_engine
from ai_employee.observability import configure_logging, request_context

# Before the app exists: uvicorn configures only its own loggers.
configure_logging()

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"

app = FastAPI(title="AI Employee", version="0.2.0")
app.add_middleware(
    SessionMiddleware, secret_key=get_settings().session_secret, same_site="lax", https_only=False
)
app.include_router(turns.router)
app.include_router(approvals.router)


@app.middleware("http")
async def correlate_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Bind one correlation id per request and echo it on the response."""
    with request_context(request.headers.get(REQUEST_ID_HEADER)) as request_id:
        started = time.perf_counter()
        response = await call_next(request)
        logger.debug(
            "%s %s -> %d in %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            time.perf_counter() - started,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _check_database() -> tuple[bool, str]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, type(exc).__name__


@app.get("/health")
def health() -> JSONResponse:
    """Each dependency reported separately, so a failure names the one that is down."""
    checks = {"database": _check_database(), "llm": llm.check_config()}
    healthy = all(ok for ok, _ in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": {name: detail for name, (_, detail) in checks.items()},
        },
    )
