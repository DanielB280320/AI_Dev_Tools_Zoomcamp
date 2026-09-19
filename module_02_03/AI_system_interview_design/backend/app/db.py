"""Engine and session plumbing — the only module that knows which database.

`LOOPBOARD_DATABASE_URL` decides. The default is a SQLite file beside the
package, so a fresh clone runs with no setup; point it at Postgres
(`postgresql+psycopg://user:pw@host/loopboard`) and nothing else in the app
changes, because every dialect-specific decision is made here:

* SQLite refuses a connection used from another thread unless
  `check_same_thread` is off, and an in-memory URL additionally needs one
  shared connection (`StaticPool`) or each caller would get its own empty
  database.
* SQLite does not enforce foreign keys unless asked, defaults to a journal
  mode that blocks readers behind a writer, and fails instantly on a locked
  file — three pragmas fix all three.
* A networked database instead wants `pool_pre_ping`, which retires the
  connections a proxy or a server restart closed underneath the pool.

The rest of the app sees only `session_scope()`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings
from .tables import Base

_engine: Engine | None = None
_new_session: sessionmaker[Session] | None = None


def _is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def _is_memory(url: str) -> bool:
    return _is_sqlite(url) and (make_url(url).database or ":memory:") == ":memory:"


def engine_options(url: str) -> dict[str, Any]:
    """Connection settings for `url`, chosen by dialect. Public for the tests."""
    options: dict[str, Any] = {"echo": settings.db_echo}
    if not _is_sqlite(url):
        options["pool_pre_ping"] = True
        return options
    options["connect_args"] = {"check_same_thread": False}
    if _is_memory(url):
        options["poolclass"] = StaticPool
    return options


def _tune_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _pragmas(connection: Any, _record: Any) -> None:
        if not isinstance(connection, sqlite3.Connection):  # pragma: no cover - other drivers
            return
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets a reader run while a writer holds the file; a no-op in memory.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Wait out a concurrent writer instead of raising "database is locked".
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def get_engine() -> Engine:
    """The process-wide engine, built on first use so the environment can be
    set (by tests, or by a `.env` loader) after this module is imported."""
    global _engine, _new_session
    if _engine is None:
        url = settings.database_url
        _engine = create_engine(url, **engine_options(url))
        if _is_sqlite(url):
            _tune_sqlite(_engine)
        _new_session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commit on a clean exit, roll back on anything else.

    `expire_on_commit` is off, so the records handed back stay readable once
    the session is closed — they are detached snapshots from there on.
    """
    get_engine()
    assert _new_session is not None
    session = _new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create anything missing. Enough while the schema only ever grows; a
    column that changes shape is the point where this wants Alembic."""
    Base.metadata.create_all(get_engine())


def dispose_engine() -> None:
    """Drop the engine and its pool, so the next call rebuilds from settings."""
    global _engine, _new_session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _new_session = None
