"""Runtime configuration, all overridable from the environment.

`LOOPBOARD_DATABASE_URL` is the one that decides where the data lives. The
numbers that matter to the contract (the 15 s cursor / presence TTL, the
4 s heartbeat the frontend uses, the ~20 s SSE keepalive) live here so the
behaviour the frontend depends on is stated once.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: The default database: a SQLite file beside the package, so it is the same
#: file wherever the server is started from.
DEFAULT_DB_FILE = Path(__file__).resolve().parent.parent / "loopboard.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DB_FILE.as_posix()}"


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    """Read once at import. Mutable so tests can override a single knob."""

    #: Any SQLAlchemy URL. SQLite by default; `postgresql+psycopg://…` and the
    #: rest work unchanged, since nothing outside `app/db.py` names a dialect.
    database_url: str = field(
        default_factory=lambda: _str("LOOPBOARD_DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    #: Log every statement the ORM emits. Loud; useful once.
    db_echo: bool = field(default_factory=lambda: _bool("LOOPBOARD_DB_ECHO", False))
    # A cursor is only returned while `now - at < cursor_ttl_ms` (spec: 15 s).
    cursor_ttl_ms: int = field(default_factory=lambda: _int("LOOPBOARD_CURSOR_TTL_MS", 15_000))
    # A participant whose heartbeat went quiet for longer than this drops off
    # the roster. The frontend beats every 4 s, so 15 s is ~3 missed beats.
    participant_ttl_ms: int = field(
        default_factory=lambda: _int("LOOPBOARD_PARTICIPANT_TTL_MS", 15_000)
    )
    prune_stale_participants: bool = field(
        default_factory=lambda: _bool("LOOPBOARD_PRUNE_STALE_PARTICIPANTS", True)
    )
    # PUT /canvas is a whole-document replace on a 120 ms debounce; cap it so a
    # runaway freehand stroke cannot pin the process.
    max_canvas_bytes: int = field(default_factory=lambda: _int("LOOPBOARD_MAX_CANVAS_BYTES", 1_000_000))
    max_canvas_nodes: int = field(default_factory=lambda: _int("LOOPBOARD_MAX_CANVAS_NODES", 5_000))
    sse_keepalive_seconds: float = field(
        default_factory=lambda: float(_int("LOOPBOARD_SSE_KEEPALIVE_SECONDS", 20))
    )
    # PBKDF2 rounds for password hashing. Lowered in tests, not in production.
    pbkdf2_iterations: int = field(
        default_factory=lambda: _int("LOOPBOARD_PBKDF2_ITERATIONS", 600_000)
    )
    seed_on_startup: bool = field(default_factory=lambda: _bool("LOOPBOARD_SEED", True))
    cors_origins: list[str] = field(
        default_factory=lambda: _csv(
            "LOOPBOARD_CORS_ORIGINS",
            [
                # The frontend's `vite dev` (8080), plus the usual Vite/Next defaults.
                "http://localhost:8080",
                "http://localhost:5173",
                "http://localhost:3000",
                "http://127.0.0.1:8080",
                "http://127.0.0.1:5173",
                "http://127.0.0.1:3000",
            ],
        )
    )


settings = Settings()
