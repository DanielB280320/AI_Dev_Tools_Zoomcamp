"""What a shared database changes about two requests arriving together.

With SQLite one writer holds the file, so a read followed by a write inside one
transaction cannot interleave with anybody else's. Postgres runs them in
parallel under READ COMMITTED, which turns two places in the store from "fine"
into races — a first cursor publish, and a join. Both are fixed in the store;
these tests are what says so, and they run against whichever database the suite
was pointed at, so the interesting run is `make test-pg`.

Threads rather than asyncio: the store is synchronous, and a thread per caller
is what uvicorn's threadpool gives these handlers anyway.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from conftest import create_session
from fastapi.testclient import TestClient

from app.models import CursorState, Role
from app.store import PALETTE, now_ms, store

CALLERS = 8


def _run(work: list) -> list:
    """Run every callable at once and re-raise whatever the first one raised."""
    with ThreadPoolExecutor(max_workers=CALLERS) as pool:
        return [future.result() for future in [pool.submit(job) for job in work]]


class TestConcurrentCursorPublishes:
    def test_a_first_publish_from_every_participant_at_once(
        self, client: TestClient, host_token: str
    ) -> None:
        """The race the read-then-insert had: every caller finds no row, every
        caller inserts, and all but one hit the primary key.

        `put_cursor` is one `INSERT … ON CONFLICT DO UPDATE`, so there is no
        window to lose — the losers update instead of failing.
        """
        session_id = create_session(client, host_token)
        at = now_ms()

        _run(
            [
                lambda index=index: store.put_cursor(
                    session_id,
                    CursorState(
                        participantId=f"p_{index}",
                        name=f"Caller {index}",
                        color=PALETTE[0],
                        x=index,
                        y=index,
                        at=at,
                    ),
                )
                for index in range(CALLERS)
            ]
        )

        cursors = store.list_cursors(session_id)
        assert len(cursors) == CALLERS, "every publish landed, none collided"
        assert {cursor.participantId for cursor in cursors} == {
            f"p_{index}" for index in range(CALLERS)
        }

    def test_one_participant_publishing_in_a_burst_keeps_one_row(
        self, client: TestClient, host_token: str
    ) -> None:
        """A moving pointer is an update, never a second row — and the last
        position published is the one stored."""
        session_id = create_session(client, host_token)
        base = now_ms()

        _run(
            [
                lambda index=index: store.put_cursor(
                    session_id,
                    CursorState(
                        participantId="p_mover",
                        name="Mover",
                        color=PALETTE[1],
                        x=index,
                        y=index,
                        at=base + index,
                    ),
                )
                for index in range(CALLERS)
            ]
        )

        cursors = store.list_cursors(session_id)
        assert len(cursors) == 1
        assert cursors[0].x in range(CALLERS), "one of the publishes won outright"


class TestConcurrentJoins:
    def test_everyone_accepting_the_link_at_once_gets_their_own_colour(
        self, client: TestClient, host_token: str
    ) -> None:
        """A join counts the roster to pick a colour and a position, then
        writes. Without the session row lock, callers that count the same
        roster pick the same colour and the same `seq`.
        """
        session_id = create_session(client, host_token)

        joined = _run(
            [
                lambda index=index: store.join(session_id, f"Guest {index}", Role.candidate)
                for index in range(CALLERS)
            ]
        )

        participants = [record for record, _token in joined]
        assert len({record.id for record in participants}) == CALLERS
        assert len({record.seq for record in participants}) == CALLERS, (
            "join order is a total order"
        )
        expected = {PALETTE[index % len(PALETTE)] for index in range(CALLERS)}
        assert {record.color for record in participants} == expected

    def test_the_roster_reads_back_in_join_order(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)

        _run(
            [
                lambda index=index: store.join(session_id, f"Guest {index}", Role.observer)
                for index in range(CALLERS)
            ]
        )

        roster = store.list_participants(session_id)
        assert len(roster) == CALLERS
        assert [record.seq for record in roster] == sorted(record.seq for record in roster)
