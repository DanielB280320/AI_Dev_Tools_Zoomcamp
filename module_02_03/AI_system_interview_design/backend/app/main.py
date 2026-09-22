"""Application wiring: middleware, error handlers, routers, demo seed."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import __version__, routers
from .config import settings
from .db import bootstrap_lock, check_connection, init_db, safe_url
from .errors import ApiError, register_error_handlers
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
    """Create anything missing in the database, then seed it if it is empty.

    Under `bootstrap_lock`, because on a shared database (Postgres) this is not
    the only process starting: two workers that both find no tables, or both
    find no sessions, would otherwise both try to create and both try to seed.

    `check_connection` goes first so an unreachable database is one readable
    error rather than a pool traceback, and the URL is logged either way —
    "which database am I actually talking to" is the first question asked of a
    server that is up but not showing the data someone expected.
    """
    check_connection()
    logging.getLogger("uvicorn.error").info("Database: %s", safe_url())
    with bootstrap_lock():
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

    if settings.static_dir:
        mount_frontend(app, Path(settings.static_dir))

    return app


#: Paths that belong to the API; a miss under them is a JSON 404, never the app shell.
API_PREFIXES = ("auth", "sessions", "assets")


def mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the frontend's SPA build: real files as-is, every other GET path the
    app shell, so client-side routes like `/session/{id}` survive a reload.

    Registered after the API routes, so those always win.
    """
    root = static_dir.resolve()
    shell = root / "_shell.html"
    if not shell.is_file():
        raise RuntimeError(f"LOOPBOARD_STATIC_DIR={static_dir} has no _shell.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        if path.split("/", 1)[0] in API_PREFIXES:
            raise ApiError(404, "not_found")
        return FileResponse(shell)


app = create_app()
