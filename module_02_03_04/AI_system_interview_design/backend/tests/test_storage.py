"""The storage layer itself: persistence, configuration, and portability.

These are the tests that would have failed against the old in-memory dict —
data outliving the process — plus the ones that keep the schema honest about
being database-agnostic, since the suite itself only ever runs on SQLite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import auth, create_session, login
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

from app.config import Settings, normalize_database_url, settings
from app.db import check_connection, dispose_engine, engine_options, safe_url
from app.main import app
from app.models import ArrowNode, PointEndpoint, ShapeEndpoint, ShapeNode, StrokeNode, TextNode
from app.store import store
from app.tables import Base


def _shape(node_id: str, label: str = "Service") -> ShapeNode:
    return ShapeNode(
        id=node_id, kind="service", label=label, x=10, y=20, w=160, h=80, authorId="p_author"
    )


@pytest.fixture
def file_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a real SQLite file for the duration of one test.

    Disposing the engine on the way in and out is what makes "restart"
    testable: the next call rebuilds it from `settings`, with nothing cached in
    between.
    """
    path = tmp_path / "loopboard.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{path.as_posix()}")
    dispose_engine()
    store.reset()
    yield path
    dispose_engine()


class TestPersistence:
    def test_a_board_outlives_the_process(self, file_db: Path) -> None:
        account = store.create_account("nina@example.com", "Nina", "not-a-real-hash")
        record = store.create_session(account.id, "Design a queue", "Nina")
        store.set_doc(record.id, [_shape("n_one"), _shape("n_two")])

        dispose_engine()  # as if the server had stopped and started again

        assert file_db.exists(), "the configured file is where the data went"
        again = store.get_session(record.id)
        assert again is not None
        assert again.title == "Design a queue"
        assert [node.id for node in store.get_doc(record.id)] == ["n_one", "n_two"]

    def test_a_restarted_server_keeps_its_sessions_and_tokens(self, file_db: Path) -> None:
        with TestClient(app) as first:
            token = login(first)
            create_session(first, token, title="Persisted")
            before = first.get("/sessions", headers=auth(token)).json()

        dispose_engine()

        with TestClient(app) as second:
            assert second.get("/auth/me", headers=auth(token)).status_code == 200, (
                "a token issued before the restart still resolves"
            )
            assert second.get("/sessions", headers=auth(token)).json() == before

    def test_the_seed_does_not_run_twice(self, file_db: Path) -> None:
        """Seeding is skipped once the database has anything in it."""
        with TestClient(app) as first:
            seeded = first.get("/health").json()["sessions"]

        dispose_engine()

        with TestClient(app) as second:
            assert second.get("/health").json()["sessions"] == seeded


class TestConfiguration:
    def test_the_url_decides_where_the_data_goes(self, file_db: Path) -> None:
        assert str(file_db) in settings.database_url
        store.create_account("solo@example.com", "Solo", "not-a-real-hash")

        assert file_db.stat().st_size > 0

    def test_sqlite_in_memory_shares_one_connection(self) -> None:
        """Without `StaticPool` every caller would open its own empty database."""
        options = engine_options("sqlite://")

        assert options["poolclass"] is StaticPool
        assert options["connect_args"] == {"check_same_thread": False}

    def test_a_sqlite_file_is_pooled_normally(self) -> None:
        options = engine_options("sqlite:///loopboard.db")

        assert "poolclass" not in options
        assert options["connect_args"] == {"check_same_thread": False}

    def test_a_server_database_gets_a_pool_and_no_sqlite_flags(self) -> None:
        options = engine_options("postgresql+psycopg://user:pw@db.internal/loopboard")

        assert options["pool_pre_ping"] is True, "replace a connection closed underneath us"
        assert options["pool_size"] == settings.db_pool_size
        assert options["max_overflow"] == settings.db_max_overflow
        assert options["pool_recycle"] == settings.db_pool_recycle_seconds
        assert "poolclass" not in options
        assert "check_same_thread" not in options["connect_args"], "that flag is SQLite's"

    def test_postgres_fails_fast_instead_of_hanging(self) -> None:
        """Without a connect timeout, an unreachable server holds the request
        open for however long the OS takes to give up."""
        options = engine_options("postgresql+psycopg://user:pw@db.internal/loopboard")

        assert options["connect_args"]["connect_timeout"] == settings.db_connect_timeout_seconds
        assert options["connect_args"]["application_name"] == "loopboard"

    def test_pool_recycle_can_be_turned_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """0 means "never recycle", which SQLAlchemy spells -1."""
        monkeypatch.setattr(settings, "db_pool_recycle_seconds", 0)

        assert engine_options("postgresql://user:pw@db.internal/loopboard")["pool_recycle"] == -1


class TestPostgresUrls:
    """The URL a person actually has is rarely the one SQLAlchemy wants."""

    @pytest.mark.parametrize(
        "given",
        [
            "postgresql://sdip:sdip@localhost:5432/sdip",  # the documentation spelling
            "postgres://sdip:sdip@localhost:5432/sdip",  # what a hosted database hands out
        ],
    )
    def test_a_driverless_url_gets_psycopg(self, given: str) -> None:
        """SQLAlchemy's default for both is psycopg2, which is not installed."""
        assert (
            normalize_database_url(given) == "postgresql+psycopg://sdip:sdip@localhost:5432/sdip"
        )

    @pytest.mark.parametrize(
        "given",
        [
            "postgresql+psycopg://user:pw@host/db",
            "postgresql+asyncpg://user:pw@host/db",
            "sqlite:///loopboard.db",
            "sqlite://",
            "mysql+pymysql://user:pw@host/db",
        ],
    )
    def test_a_url_that_names_its_driver_is_left_alone(self, given: str) -> None:
        assert normalize_database_url(given) == given

    def test_the_setting_normalises_on_the_way_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """So `LOOPBOARD_DATABASE_URL=postgres://…` reaches the engine usable."""
        monkeypatch.setenv("LOOPBOARD_DATABASE_URL", "postgres://sdip:sdip@localhost/sdip")

        assert Settings().database_url == "postgresql+psycopg://sdip:sdip@localhost/sdip"


class TestUnreachableDatabase:
    """A wrong URL is the normal first experience of a new database, so the
    failure has to say which URL was tried and what to do — not forty frames of
    connection pool with one useful line scrolled off the top.
    """

    @staticmethod
    def _failure(url: str, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setattr(settings, "database_url", normalize_database_url(url))
        dispose_engine()
        with pytest.raises(RuntimeError) as raised:
            check_connection()
        dispose_engine()
        return str(raised.value)

    def test_a_container_name_says_to_use_localhost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The trap this came from: a container name resolves inside a Docker
        network and nowhere else, and the URL is copied out of a `docker run`."""
        message = self._failure("postgresql://sdip:sdip@no-such-container:5432/sdip", monkeypatch)

        assert "Cannot reach the database" in message
        assert "no-such-container" in message
        assert "localhost" in message
        assert "Docker" in message

    def test_a_dead_port_says_to_start_the_database(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        message = self._failure("postgresql://sdip:sdip@127.0.0.1:5999/sdip", monkeypatch)

        assert "make db-up" in message

    def test_every_failure_offers_the_sqlite_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        message = self._failure("postgresql://sdip:sdip@127.0.0.1:5999/sdip", monkeypatch)

        assert "Unset LOOPBOARD_DATABASE_URL" in message

    def test_the_password_is_never_printed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The message is going into a terminal, a log aggregator and probably
        a bug report."""
        message = self._failure("postgresql://sdip:hunter2@127.0.0.1:5999/sdip", monkeypatch)

        assert "hunter2" not in message
        assert "sdip:***@" in message

    def test_a_reachable_database_raises_nothing(self, file_db: Path) -> None:
        assert check_connection() is None


class TestSafeUrl:
    def test_the_password_is_masked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:secret@h/db")

        assert safe_url() == "postgresql+psycopg://u:***@h/db"

    def test_a_sqlite_path_survives_intact(self) -> None:
        """Nothing to hide, and the path is the useful part."""
        assert safe_url("sqlite:///loopboard.db") == "sqlite:///loopboard.db"


class TestPortability:
    def test_the_schema_compiles_for_postgres(self) -> None:
        """No driver needed to prove the DDL is not SQLite-only."""
        statements = [
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
            for table in Base.metadata.sorted_tables
        ]

        assert len(statements) == 6
        assert any("JSONB" in statement for statement in statements), "nodes stay JSONB on PG"
        assert not any("DATETIME" in statement for statement in statements), "millis, not dates"

    def test_enums_are_stored_as_their_wire_values(self) -> None:
        """VARCHAR holding the wire value, not a native enum type — so adding a
        role is a code change, not a migration."""
        role = Base.metadata.tables["participants"].columns["role"].type

        assert role.enums == ["interviewer", "candidate", "observer"]
        assert "VARCHAR" in str(role.compile(dialect=postgresql.dialect()))


class TestNodeRoundTrip:
    def test_every_node_type_survives_json(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)
        nodes = [
            _shape("n_shape"),
            ArrowNode(
                id="n_arrow",
                from_=ShapeEndpoint(shapeId="n_shape"),
                to=PointEndpoint(x=5.5, y=-2.25),
                label="writes",
                dashed=True,
                bidirectional=False,
                authorId="p_author",
            ),
            StrokeNode(
                id="n_stroke",
                points=[[0, 0], [1.5, 2.5]],
                color="#37d6c3",
                width=3,
                authorId="p_author",
            ),
            TextNode(id="n_text", x=1, y=2, text="10:1 read:write", authorId="p_author"),
        ]

        store.set_doc(session_id, nodes)

        assert store.get_doc(session_id) == nodes, "including ArrowNode's `from` alias"

    def test_z_order_is_the_stored_order(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)
        store.set_doc(session_id, [_shape("n_a"), _shape("n_b"), _shape("n_c")])

        store.upsert_nodes(session_id, [_shape("n_b", label="edited"), _shape("n_d")])

        doc = store.get_doc(session_id)
        assert [node.id for node in doc] == ["n_a", "n_b", "n_c", "n_d"], "edits stay in place"
        assert doc[1].label == "edited"

    def test_a_repeated_id_in_one_document_collapses(
        self, client: TestClient, host_token: str
    ) -> None:
        """A node id is the key, so the last write for an id wins its first slot."""
        session_id = create_session(client, host_token)

        store.set_doc(session_id, [_shape("n_a"), _shape("n_b"), _shape("n_a", label="again")])

        doc = store.get_doc(session_id)
        assert [node.id for node in doc] == ["n_a", "n_b"]
        assert doc[0].label == "again"
