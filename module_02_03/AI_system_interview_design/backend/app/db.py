"""Engine and session plumbing — the only module that knows which database.

`LOOPBOARD_DATABASE_URL` decides. The default is a SQLite file beside the
package, so a fresh clone runs with no setup; point it at Postgres
(`postgresql://user:pw@host/loopboard`) and nothing else in the app changes,
because every dialect-specific decision is made here:

* SQLite refuses a connection used from another thread unless
  `check_same_thread` is off, and an in-memory URL additionally needs one
  shared connection (`StaticPool`) or each caller would get its own empty
  database.
* SQLite does not enforce foreign keys unless asked, defaults to a journal
  mode that blocks readers behind a writer, and fails instantly on a locked
  file — three pragmas fix all three.
* Postgres is reached over a socket, so it gets a real pool instead: sized
  connections, `pool_pre_ping` to retire the ones a proxy or a server restart
  closed underneath it, `pool_recycle` to stay under an idle timeout, and a
  connect timeout so an unreachable server fails fast instead of hanging.

The two differences that outlive configuration are here as well:

* `bootstrap_lock()` — SQLite is one process, Postgres is shared, so "create
  the tables, then seed if empty" has to be serialised across whatever else is
  starting at the same moment.
* `upsert()` — read-then-insert is safe under SQLite's single writer and racy
  on Postgres, so the one hot upsert in the app (cursor publishes, ~11 Hz per
  participant) is pushed into the database as `ON CONFLICT DO UPDATE`.

A SQLite file cannot really be unreachable, and a Postgres URL is wrong more
often than it is right the first time, so `check_connection()` turns the
driver's failure into a sentence that says which URL was tried and what to do
about it — the traceback underneath names about forty frames of connection pool
and one useful line.

The rest of the app sees only `session_scope()`.
"""

from __future__ import annotations

import sqlite3
import threading
import zlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
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


def _is_postgres(url: str) -> bool:
    return make_url(url).get_backend_name() == "postgresql"


def is_postgres() -> bool:
    """Whether the configured database is Postgres. The callers are the two
    places a shared server behaves differently from a local file."""
    return _is_postgres(settings.database_url)


def engine_options(url: str) -> dict[str, Any]:
    """Connection settings for `url`, chosen by dialect. Public for the tests."""
    options: dict[str, Any] = {"echo": settings.db_echo}
    if _is_sqlite(url):
        options["connect_args"] = {"check_same_thread": False}
        if _is_memory(url):
            options["poolclass"] = StaticPool
        return options
    # Any networked database: pre-ping so a connection the server or a proxy
    # closed underneath the pool is replaced rather than handed to a request.
    options["pool_pre_ping"] = True
    options["pool_size"] = settings.db_pool_size
    options["max_overflow"] = settings.db_max_overflow
    options["pool_recycle"] = settings.db_pool_recycle_seconds or -1
    if _is_postgres(url):
        options["connect_args"] = {
            "connect_timeout": settings.db_connect_timeout_seconds,
            # Names this app in `pg_stat_activity`, so a held connection can be
            # traced back to it rather than to "unknown".
            "application_name": "loopboard",
        }
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


def safe_url(url: str | None = None) -> str:
    """The configured URL with its password masked, safe to print or log."""
    return make_url(url or settings.database_url).render_as_string(hide_password=True)


def _in_container() -> bool:
    """Whether this process is itself inside a container, which decides whether
    a container name is a plausible host or a copy-paste mistake."""
    return Path("/.dockerenv").exists()


def _advice(url: str, detail: str) -> list[str]:
    """What to suggest for a connection that did not open, most specific first."""
    host = make_url(url).host or ""
    lowered = detail.lower()
    tips: list[str] = []

    unresolved = "resolve host" in lowered or "translate host name" in lowered
    if unresolved and not _in_container():
        tips.append(
            f"{host!r} does not resolve from this machine. A Docker container name only "
            "resolves inside a Docker network — from the host, use `localhost` and the "
            "port the container publishes."
        )
    elif unresolved:
        tips.append(
            f"{host!r} does not resolve. Inside a container, `localhost` is that "
            "container: reach a database on the host via `host.docker.internal` (with "
            "`--add-host=host.docker.internal:host-gateway`), or put both on one network "
            "and use the container name."
        )
    elif "refused" in lowered or "timeout" in lowered or "timed out" in lowered:
        tips.append(
            "Nothing is accepting connections there. Start the database "
            "(`make db-up` for the local container) and check the port."
        )
    elif "password" in lowered or "authentication" in lowered or "role" in lowered:
        tips.append("The database rejected these credentials — check the user and password.")
    elif "does not exist" in lowered:
        tips.append("The server is up but has no such database — check the name in the URL.")

    tips.append(
        "Unset LOOPBOARD_DATABASE_URL to fall back to the default SQLite file, which "
        "needs no server."
    )
    return tips


def check_connection() -> None:
    """Open one connection now, so a bad URL fails with an explanation.

    Called at startup, before anything else touches the database. Without it the
    first failure surfaces from wherever the pool happened to be used, as a
    SQLAlchemy traceback whose single informative line is at the very top and
    scrolled away.
    """
    try:
        with get_engine().connect():
            return
    except OperationalError as error:
        detail = str(error.orig or error).strip().splitlines()[0]

    lines = [
        "Cannot reach the database.",
        "",
        f"  URL:    {safe_url()}",
        f"  Driver: {detail}",
        "",
    ]
    lines += [f"  * {tip}" for tip in _advice(settings.database_url, detail)]
    # `from None`: the driver's own message is quoted above, and the chain it
    # would print is the pool internals that got us here, not the cause.
    raise RuntimeError("\n".join(lines)) from None


#: A constant for `pg_advisory_lock`, which keys on a 64-bit integer rather
#: than a name. Any stable number works; this one is derived from a string so
#: it cannot collide with another application's hand-picked lock id.
_BOOTSTRAP_LOCK_KEY = zlib.crc32(b"loopboard.bootstrap")


@contextmanager
def bootstrap_lock() -> Iterator[None]:
    """Hold the startup lock while the schema is created and the seed decided.

    Startup is read-then-write twice over — `create_all` asks which tables
    exist before creating them, and the seed asks whether the database is empty
    before filling it. With a SQLite file that is one process and the question
    cannot go stale. Postgres is shared, so two workers (or a rolling deploy
    overlapping the old one) can both see no tables, or both see zero sessions,
    and the loser crashes on a duplicate `accounts.email`.

    A session-level advisory lock serialises them: the second worker waits, and
    by the time it looks the database is already seeded, so it seeds nothing.
    The lock is advisory — it blocks only other holders of the same key — and
    is released explicitly, and by the server anyway if this process dies
    holding it.

    Anywhere else this is a no-op: one process, nothing to serialise against.
    """
    if not is_postgres():
        yield
        return
    # Its own connection, not a pooled session: the lock has to outlive each of
    # the transactions taken inside the block.
    with get_engine().connect() as connection:
        connection.execute(sa.text("SELECT pg_advisory_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY})
        connection.commit()
        try:
            yield
        finally:
            connection.execute(
                sa.text("SELECT pg_advisory_unlock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
            )
            connection.commit()


#: Guards the read-then-write transactions below, within this process.
_write_lock = threading.Lock()


@contextmanager
def serialized_write() -> Iterator[None]:
    """Serialise a transaction that reads a value and then writes based on it.

    Two of these exist in the store, both picking "the next number" — a join's
    place in the roster, and a cursor's place in the list. Neither dialect
    makes them safe on its own, and each needs a different fix:

    * **Postgres** runs transactions in parallel under READ COMMITTED, so the
      callers must agree on a row to queue behind. That is `FOR UPDATE` on the
      session row, taken inside the transaction by the query itself — it works
      across processes, which is the point, since a deployment runs several
      workers. This context manager is a no-op there; holding a process-local
      lock as well would only serialise one worker against itself.

    * **SQLite** looks safe and is not. A transaction begins deferred, taking
      no lock until the first write, so two callers can both read the same
      count before either inserts — and `FOR UPDATE` is not in its grammar, so
      the query above does nothing. `BEGIN IMMEDIATE` would fix it at the
      driver level; a lock here fixes it without reaching into connection
      handling, and costs nothing, because SQLite is the single-process case by
      definition (the SSE broker is per-process, so two servers over one file
      was never a supported deployment).

    Taken around `session_scope`, never inside it: the lock has to be released
    after the commit, or the next caller reads the same stale value anyway.
    """
    if is_postgres():
        yield
        return
    with _write_lock:
        yield


def upsert(db: Session, model: type, values: dict[str, Any], update: Sequence[str]) -> None:
    """Insert `values`, or update `update`'s columns if the key is taken.

    One statement, so there is no window between the check and the write. Both
    dialects the app runs on spell this `INSERT … ON CONFLICT DO UPDATE`; they
    just export it from different modules, because it is not standard SQL.

    The read-then-insert this replaces is fine under SQLite, where one writer
    holds the file, and loses a race on Postgres — two participants publishing
    a first cursor at the same moment would both find no row and both insert,
    and one of them would get a primary key violation.
    """
    table = model.__table__
    if _is_postgres(settings.database_url):
        from sqlalchemy.dialects.postgresql import insert
    elif _is_sqlite(settings.database_url):
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover - no other dialect is supported
        db.merge(model(**values))
        return
    statement = insert(table).values(**values)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[column.name for column in table.primary_key],
            set_={name: getattr(statement.excluded, name) for name in update},
        )
    )


def dispose_engine() -> None:
    """Drop the engine and its pool, so the next call rebuilds from settings."""
    global _engine, _new_session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _new_session = None
