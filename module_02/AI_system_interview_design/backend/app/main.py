"""Application wiring: middleware, error handlers, routers, demo seed."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, routers
from .config import settings
from .db import init_db
from .errors import register_error_handlers
from .seed import seed
from .store import store

DESCRIPTION = """
Backend for Loopboard, the system design interview platform — the server side of
`openapi.yaml`.

An interviewer signs in, creates a *session* (a shared architecture canvas) and
shares the join link; candidates and observers join it anonymously with a display
name. Everyone edits the same document and sees each other's cursors. Ending a
session freezes the board read-only; it can be reopened.

All timestamps on the wire are epoch **milliseconds**.

Storage is a SQL database — SQLite by default, any SQLAlchemy URL via
`LOOPBOARD_DATABASE_URL` — seeded with demo data while it is still empty.
Sign in as `alex@loopboard.dev` / `loopboard-demo` to see the seeded boards.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create anything missing in the database, then seed it if it is empty."""
    init_db()
    if settings.seed_on_startup and store.session_count() == 0:
        seed(store)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Loopboard API",
        version=__version__,
        summary="Backend contract expected by the Loopboard frontend.",
        description=DESCRIPTION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(routers.auth.router)
    app.include_router(routers.sessions.router)
    app.include_router(routers.participants.router)
    app.include_router(routers.cursors.router)
    app.include_router(routers.canvas.router)
    app.include_router(routers.events.router)

    @app.get("/health", operation_id="healthCheck", tags=["Meta"], summary="Liveness probe")
    async def health() -> dict[str, str | int]:
        return {"status": "ok", "sessions": store.session_count()}

    return app


app = create_app()
