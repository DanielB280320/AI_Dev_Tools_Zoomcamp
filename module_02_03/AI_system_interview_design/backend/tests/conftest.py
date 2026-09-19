"""Shared fixtures.

Every test starts from an empty database seeded with the demo data, so the seed
is exercised by every run, and runs against a `TestClient` entered as a context
manager — the lifespan has to run for the SSE broker to share one event loop
across requests.

The database is a throwaway SQLite file, pointed at through the same setting a
deployment would use to reach Postgres. The `row` helpers below reach past the
store into the tables, for the handful of tests that have to age a timestamp or
count what a delete left behind.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Must be set before `app.config` is imported: the settings are read once.
os.environ.setdefault("LOOPBOARD_PBKDF2_ITERATIONS", "1000")  # keep the suite fast
os.environ.setdefault("LOOPBOARD_SSE_KEEPALIVE_SECONDS", "1")

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import settings
from app.db import dispose_engine, session_scope
from app.events import broker
from app.main import app
from app.seed import DEMO_PASSWORD, RATE_LIMITER_ID, URL_SHORTENER_ID
from app.store import store

ALEX = "alex@loopboard.dev"
SAM = "sam@loopboard.dev"

__all__ = ["ALEX", "DEMO_PASSWORD", "RATE_LIMITER_ID", "SAM", "URL_SHORTENER_ID"]


@pytest.fixture
def client() -> TestClient:
    store.reset()
    broker.reset()
    with TestClient(app) as test_client:
        yield test_client
    store.reset()
    broker.reset()


@pytest.fixture(scope="session", autouse=True)
def test_database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Run the whole suite against one throwaway SQLite file.

    A file rather than `sqlite://`: an in-memory database only exists inside the
    connection that opened it, so every thread would have to share one — and the
    SSE tests run a second server on a thread of its own.
    """
    path = tmp_path_factory.mktemp("loopboard") / "test.db"
    settings.database_url = f"sqlite:///{path.as_posix()}"
    dispose_engine()
    yield path
    dispose_engine()


# ------------------------------ raw table access ----------------------------


def get_row(model: type, key: object) -> object | None:
    """One row by primary key, detached."""
    with session_scope() as db:
        return db.get(model, key)


def all_rows(model: type) -> list[object]:
    """Every row of one table, detached."""
    with session_scope() as db:
        return list(db.scalars(sa.select(model)))


def count_rows(model: type, **filters: object) -> int:
    """How many rows of `model` match — used to prove a delete cascaded."""
    with session_scope() as db:
        where = [getattr(model, column) == value for column, value in filters.items()]
        return db.scalar(sa.select(sa.func.count()).select_from(model).where(*where)) or 0


def update_row(model: type, key: object, **fields: object) -> None:
    """Poke a stored row directly, to set up a state the API cannot reach —
    a `createdAt` in the past, a locked board, a heartbeat that went quiet."""
    with session_scope() as db:
        row = db.get(model, key)
        assert row is not None, f"no {model.__name__} with key {key!r}"
        for name, value in fields.items():
            setattr(row, name, value)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, email: str = ALEX, password: str = DEMO_PASSWORD) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.fixture
def host_token(client: TestClient) -> str:
    """An `interviewerAuth` token for the seeded account that owns most boards."""
    return login(client)


@dataclass
class Member:
    """A joined participant plus its `participantAuth` token."""

    id: str
    name: str
    role: str
    color: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return auth(self.token)


def join(client: TestClient, session_id: str, name: str, role: str) -> Member:
    response = client.post(
        f"/sessions/{session_id}/participants", json={"name": name, "role": role}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Member(
        id=body["id"],
        name=body["name"],
        role=body["role"],
        color=body["color"],
        token=body["token"],
    )


def create_session(
    client: TestClient,
    token: str,
    title: str = "Design a thing",
    host_name: str = "Alex Rivera",
) -> str:
    response = client.post(
        "/sessions",
        json={"title": title, "hostName": host_name},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@dataclass
class Board:
    """A fresh session with one of each role already joined."""

    id: str
    host_token: str
    interviewer: Member
    candidate: Member
    observer: Member


@pytest.fixture
def board(client: TestClient, host_token: str) -> Board:
    session_id = create_session(client, host_token)
    return Board(
        id=session_id,
        host_token=host_token,
        interviewer=join(client, session_id, "Alex Rivera", "interviewer"),
        candidate=join(client, session_id, "Jordan Hale", "candidate"),
        observer=join(client, session_id, "Priya Natarajan", "observer"),
    )
