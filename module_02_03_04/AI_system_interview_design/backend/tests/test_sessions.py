"""Session lifecycle: create, list, read, end, reopen, delete."""

from __future__ import annotations

from conftest import (
    RATE_LIMITER_ID,
    URL_SHORTENER_ID,
    auth,
    count_rows,
    create_session,
    join,
    login,
    update_row,
)
from fastapi.testclient import TestClient

from app import tables
from app.store import store

SESSION_KEYS = {"id", "title", "hostName", "status", "createdAt", "endedAt", "canvasLocked"}


class TestCreate:
    def test_creates_a_live_empty_session(self, client: TestClient, host_token: str) -> None:
        response = client.post(
            "/sessions",
            json={"title": "  Design a URL shortener  ", "hostName": " Alex "},
            headers=auth(host_token),
        )

        assert response.status_code == 201
        body = response.json()
        assert set(body) == SESSION_KEYS, "no extra or missing keys on the wire"
        assert body["title"] == "Design a URL shortener", "strings are trimmed"
        assert body["hostName"] == "Alex"
        assert body["status"] == "live"
        assert body["endedAt"] is None, "the key is present even when null"
        assert body["canvasLocked"] is False
        assert len(body["id"]) == 16

        canvas = client.get(
            f"/sessions/{body['id']}/canvas",
            headers=join(client, body["id"], "Alex", "interviewer").headers,
        )
        assert canvas.json() == {"nodes": []}

    def test_blank_strings_fall_back(self, client: TestClient, host_token: str) -> None:
        response = client.post(
            "/sessions", json={"title": "   ", "hostName": ""}, headers=auth(host_token)
        )

        body = response.json()
        assert body["title"] == "Untitled interview"
        assert body["hostName"] == "Interviewer"

    def test_timestamps_are_epoch_milliseconds(self, client: TestClient, host_token: str) -> None:
        created_at = client.post(
            "/sessions", json={"title": "T", "hostName": "H"}, headers=auth(host_token)
        ).json()["createdAt"]

        # Milliseconds since 1970 passed 1.7e12 in 2023; seconds are ~1.7e9.
        assert created_at > 1_700_000_000_000

    def test_requires_an_interviewer_token(self, client: TestClient) -> None:
        response = client.post("/sessions", json={"title": "T", "hostName": "H"})

        assert response.status_code == 401

    def test_rejects_unknown_fields_and_over_long_title(
        self, client: TestClient, host_token: str
    ) -> None:
        extra = client.post(
            "/sessions",
            json={"title": "T", "hostName": "H", "status": "ended"},
            headers=auth(host_token),
        )
        long_title = client.post(
            "/sessions", json={"title": "x" * 201, "hostName": "H"}, headers=auth(host_token)
        )

        assert extra.status_code == 400
        assert long_title.status_code == 400


class TestList:
    def test_sorted_newest_first(self, client: TestClient, host_token: str) -> None:
        for title in ("first", "second", "third"):
            create_session(client, host_token, title=title)

        body = client.get("/sessions", headers=auth(host_token)).json()

        timestamps = [session["createdAt"] for session in body]
        assert timestamps == sorted(timestamps, reverse=True)
        assert body[0]["title"] == "third", "the seeded boards are older than these"

    def test_ties_on_created_at_still_list_newest_first(
        self, client: TestClient, host_token: str
    ) -> None:
        """Three sessions created inside one millisecond must not invert."""
        ids = [create_session(client, host_token, title=name) for name in ("a", "b", "c")]
        for session_id in ids:
            update_row(tables.SessionRecord, session_id, created_at=1_789_000_000_000)

        body = client.get("/sessions", headers=auth(host_token)).json()

        tied = [session["id"] for session in body if session["id"] in set(ids)]
        assert tied == list(reversed(ids)), "the last created comes first"

    def test_includes_live_and_ended(self, client: TestClient, host_token: str) -> None:
        body = client.get("/sessions", headers=auth(host_token)).json()

        statuses = {session["status"] for session in body}
        assert statuses == {"live", "ended"}

    def test_scoped_to_the_calling_interviewer(self, client: TestClient, host_token: str) -> None:
        sam_token = login(client, "sam@loopboard.dev")

        alex_ids = {s["id"] for s in client.get("/sessions", headers=auth(host_token)).json()}
        sam_ids = {s["id"] for s in client.get("/sessions", headers=auth(sam_token)).json()}

        assert URL_SHORTENER_ID in alex_ids
        assert URL_SHORTENER_ID not in sam_ids
        assert not alex_ids & sam_ids


class TestRead:
    def test_is_public(self, client: TestClient) -> None:
        """The join page reads a session before the visitor has any identity."""
        response = client.get(f"/sessions/{URL_SHORTENER_ID}")

        assert response.status_code == 200
        assert set(response.json()) == SESSION_KEYS

    def test_unknown_session_is_404_not_an_empty_200(self, client: TestClient) -> None:
        response = client.get("/sessions/nosuchsessionid")

        assert response.status_code == 404
        assert response.json()["error"] == "session_not_found"

    def test_a_deleted_session_is_404(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)
        client.delete(f"/sessions/{session_id}", headers=auth(host_token))

        assert client.get(f"/sessions/{session_id}").status_code == 404


class TestEndAndReopen:
    def test_end_freezes_and_reopen_thaws(self, client: TestClient, board) -> None:
        ended = client.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)

        assert ended.status_code == 200
        assert ended.json()["status"] == "ended"
        assert ended.json()["canvasLocked"] is True
        assert ended.json()["endedAt"] is not None

        reopened = client.post(f"/sessions/{board.id}/reopen", headers=board.interviewer.headers)

        assert reopened.json()["status"] == "live"
        assert reopened.json()["canvasLocked"] is False
        assert reopened.json()["endedAt"] is None

    def test_the_owning_interviewer_token_also_works(self, client: TestClient, board) -> None:
        response = client.post(f"/sessions/{board.id}/end", headers=auth(board.host_token))

        assert response.status_code == 200

    def test_candidates_and_observers_cannot_end(self, client: TestClient, board) -> None:
        for member in (board.candidate, board.observer):
            response = client.post(f"/sessions/{board.id}/end", headers=member.headers)

            assert response.status_code == 403
            assert response.json()["error"] == "forbidden_role"

        assert client.get(f"/sessions/{board.id}").json()["status"] == "live"

    def test_unauthenticated_and_unknown_session(self, client: TestClient, board) -> None:
        assert client.post(f"/sessions/{board.id}/end").status_code == 401
        assert (
            client.post(
                "/sessions/nosuchsessionid/end", headers=board.interviewer.headers
            ).status_code
            == 404
        )


class TestDelete:
    def test_deletes_everything_in_the_session(self, client: TestClient, board) -> None:
        response = client.delete(f"/sessions/{board.id}", headers=auth(board.host_token))

        assert response.status_code == 204
        assert store.get_session(board.id) is None
        for model in (tables.CanvasNodeRow, tables.CursorRow, tables.ParticipantRecord,
                      tables.TokenRecord):
            assert count_rows(model, session_id=board.id) == 0, model.__name__

    def test_is_idempotent(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)

        first = client.delete(f"/sessions/{session_id}", headers=auth(host_token))
        second = client.delete(f"/sessions/{session_id}", headers=auth(host_token))

        assert first.status_code == second.status_code == 204

    def test_another_interviewer_cannot_delete(self, client: TestClient) -> None:
        sam_token = login(client, "sam@loopboard.dev")

        response = client.delete(f"/sessions/{URL_SHORTENER_ID}", headers=auth(sam_token))

        assert response.status_code == 403
        assert store.get_session(URL_SHORTENER_ID) is not None

    def test_a_participant_token_cannot_delete(self, client: TestClient, board) -> None:
        response = client.delete(f"/sessions/{board.id}", headers=board.interviewer.headers)

        assert response.status_code == 401, "deletion needs an account, not a session token"
        assert store.get_session(board.id) is not None


class TestSeededEndedSession:
    def test_is_frozen_and_reviewable(self, client: TestClient) -> None:
        session = client.get(f"/sessions/{RATE_LIMITER_ID}").json()

        assert session["status"] == "ended"
        assert session["canvasLocked"] is True
        assert session["endedAt"] > session["createdAt"]
