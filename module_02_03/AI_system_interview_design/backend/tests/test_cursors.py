"""Cursor publish / poll, including the 15 s freshness window."""

from __future__ import annotations

from conftest import URL_SHORTENER_ID, auth, join
from fastapi.testclient import TestClient

from app.config import settings
from app.store import now_ms, store

CURSOR_KEYS = {"participantId", "name", "color", "x", "y", "at"}


def cursor(member, x: float = 120.5, y: float = -40.25, at: int | None = None) -> dict:
    return {
        "participantId": member.id,
        "name": member.name,
        "color": member.color,
        "x": x,
        "y": y,
        "at": at if at is not None else now_ms(),
    }


class TestPublish:
    def test_publishes_and_reads_back(self, client: TestClient, board) -> None:
        payload = cursor(board.candidate)

        published = client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json=payload,
            headers=board.candidate.headers,
        )

        assert published.status_code == 204
        body = client.get(f"/sessions/{board.id}/cursors", headers=board.interviewer.headers).json()
        assert len(body) == 1
        assert set(body[0]) == CURSOR_KEYS
        assert body[0] == payload, "name and color are stored denormalised, as sent"

    def test_negative_canvas_space_coordinates_are_fine(self, client: TestClient, board) -> None:
        response = client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json=cursor(board.candidate, x=-4_200.75, y=-999.5),
            headers=board.candidate.headers,
        )

        assert response.status_code == 204

    def test_is_an_upsert(self, client: TestClient, board) -> None:
        for x in (10, 20, 30):
            client.put(
                f"/sessions/{board.id}/cursors/{board.candidate.id}",
                json=cursor(board.candidate, x=x),
                headers=board.candidate.headers,
            )

        body = client.get(f"/sessions/{board.id}/cursors", headers=board.candidate.headers).json()

        assert len(body) == 1
        assert body[0]["x"] == 30

    def test_cannot_publish_for_another_participant(self, client: TestClient, board) -> None:
        spoofed_path = client.put(
            f"/sessions/{board.id}/cursors/{board.observer.id}",
            json=cursor(board.observer),
            headers=board.candidate.headers,
        )
        spoofed_body = client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json=cursor(board.observer),
            headers=board.candidate.headers,
        )

        assert spoofed_path.status_code == 403
        assert spoofed_body.status_code == 403, "the body's participantId is checked too"
        assert client.get(f"/sessions/{board.id}/cursors", headers=board.candidate.headers).json() == []

    def test_observers_may_publish_their_own_cursor(self, client: TestClient, board) -> None:
        """Read-only on the canvas, but their pointer is still visible."""
        response = client.put(
            f"/sessions/{board.id}/cursors/{board.observer.id}",
            json=cursor(board.observer),
            headers=board.observer.headers,
        )

        assert response.status_code == 204

    def test_an_interviewer_account_token_has_no_cursor(self, client: TestClient, board) -> None:
        response = client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json=cursor(board.candidate),
            headers=auth(board.host_token),
        )

        assert response.status_code == 403

    def test_malformed_color_is_rejected(self, client: TestClient, board) -> None:
        payload = cursor(board.candidate) | {"color": "teal"}

        response = client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json=payload,
            headers=board.candidate.headers,
        )

        assert response.status_code == 400

    def test_requires_a_token(self, client: TestClient, board) -> None:
        response = client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}", json=cursor(board.candidate)
        )

        assert response.status_code == 401


class TestList:
    def test_omits_cursors_older_than_the_ttl(self, client: TestClient, board) -> None:
        fresh = cursor(board.candidate, at=now_ms() - 1_000)
        stale = cursor(board.observer, at=now_ms() - settings.cursor_ttl_ms - 1)
        client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json=fresh,
            headers=board.candidate.headers,
        )
        client.put(
            f"/sessions/{board.id}/cursors/{board.observer.id}",
            json=stale,
            headers=board.observer.headers,
        )

        body = client.get(f"/sessions/{board.id}/cursors", headers=board.interviewer.headers).json()

        assert [c["participantId"] for c in body] == [board.candidate.id]
        assert store.get_cursor(board.id, board.observer.id) is not None, "kept, just not served"

    def test_includes_the_callers_own_cursor(self, client: TestClient, board) -> None:
        """The frontend filters itself out by participantId; the server does not."""
        client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json=cursor(board.candidate),
            headers=board.candidate.headers,
        )

        body = client.get(f"/sessions/{board.id}/cursors", headers=board.candidate.headers).json()

        assert [c["participantId"] for c in body] == [board.candidate.id]

    def test_empty_board_has_no_cursors(self, client: TestClient, board) -> None:
        response = client.get(f"/sessions/{board.id}/cursors", headers=board.candidate.headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_seeded_cursors_are_fresh(self, client: TestClient) -> None:
        member = join(client, URL_SHORTENER_ID, "Watcher", "observer")

        body = client.get(f"/sessions/{URL_SHORTENER_ID}/cursors", headers=member.headers).json()

        assert len(body) == 2, "the seeded cursors are inside the freshness window"

    def test_requires_a_token(self, client: TestClient, board) -> None:
        assert client.get(f"/sessions/{board.id}/cursors").status_code == 401
