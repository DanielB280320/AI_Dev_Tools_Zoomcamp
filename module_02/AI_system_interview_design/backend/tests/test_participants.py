"""Join / leave, the roster, heartbeats and presence pruning."""

from __future__ import annotations

from conftest import URL_SHORTENER_ID, create_session, join
from fastapi.testclient import TestClient

from app.config import settings
from app.store import PALETTE, now_ms, store

PARTICIPANT_KEYS = {"id", "name", "role", "color", "lastSeen"}


class TestJoin:
    def test_is_public_and_returns_a_token(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)

        response = client.post(
            f"/sessions/{session_id}/participants", json={"name": " Jordan ", "role": "candidate"}
        )

        assert response.status_code == 201
        body = response.json()
        assert set(body) == PARTICIPANT_KEYS | {"token"}
        assert body["name"] == "Jordan", "names are trimmed"
        assert body["role"] == "candidate"
        assert body["id"].startswith("p_")
        assert body["token"]

    def test_blank_name_falls_back_to_guest(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)

        assert join(client, session_id, "   ", "candidate").name == "Guest"

    def test_colors_cycle_through_the_palette_by_join_order(
        self, client: TestClient, host_token: str
    ) -> None:
        session_id = create_session(client, host_token)

        colors = [
            join(client, session_id, f"p{index}", "candidate").color
            for index in range(len(PALETTE) + 2)
        ]

        assert colors[: len(PALETTE)] == list(PALETTE)
        assert colors[len(PALETTE) :] == list(PALETTE[:2]), "the palette wraps"

    def test_unknown_session_is_404(self, client: TestClient) -> None:
        response = client.post(
            "/sessions/nosuchsessionid/participants", json={"name": "Jordan", "role": "candidate"}
        )

        assert response.status_code == 404

    def test_invalid_role_is_400(self, client: TestClient, host_token: str) -> None:
        session_id = create_session(client, host_token)

        response = client.post(
            f"/sessions/{session_id}/participants", json={"name": "Jordan", "role": "admin"}
        )

        assert response.status_code == 400

    def test_joining_an_ended_session_is_allowed_read_only(self, client: TestClient, board) -> None:
        client.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)

        latecomer = join(client, board.id, "Reviewer", "candidate")

        assert client.get(f"/sessions/{board.id}/canvas", headers=latecomer.headers).status_code == 200
        write = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=latecomer.headers
        )
        assert write.status_code == 409


class TestRoster:
    def test_lists_in_join_order(self, client: TestClient, board) -> None:
        response = client.get(
            f"/sessions/{board.id}/participants", headers=board.candidate.headers
        )

        assert response.status_code == 200
        body = response.json()
        assert [p["name"] for p in body] == ["Alex Rivera", "Jordan Hale", "Priya Natarajan"]
        assert set(body[0]) == PARTICIPANT_KEYS, "no token leaks into the roster"

    def test_requires_a_token(self, client: TestClient, board) -> None:
        assert client.get(f"/sessions/{board.id}/participants").status_code == 401

    def test_drops_participants_whose_heartbeat_went_stale(
        self, client: TestClient, board
    ) -> None:
        store.touch_participant(
            board.id, board.observer.id, at=now_ms() - settings.participant_ttl_ms - 1
        )

        body = client.get(f"/sessions/{board.id}/participants", headers=board.candidate.headers).json()

        assert [p["id"] for p in body] == [board.interviewer.id, board.candidate.id]

    def test_pruning_can_be_switched_off(self, client: TestClient, board, monkeypatch) -> None:
        monkeypatch.setattr(settings, "prune_stale_participants", False)
        store.touch_participant(board.id, board.observer.id, at=0)

        body = client.get(f"/sessions/{board.id}/participants", headers=board.candidate.headers).json()

        assert len(body) == 3

    def test_seeded_board_has_a_roster(self, client: TestClient) -> None:
        member = join(client, URL_SHORTENER_ID, "Late observer", "observer")

        body = client.get(
            f"/sessions/{URL_SHORTENER_ID}/participants", headers=member.headers
        ).json()

        assert [p["role"] for p in body[:3]] == ["interviewer", "candidate", "observer"]


class TestHeartbeat:
    def test_refreshes_last_seen(self, client: TestClient, board) -> None:
        store.touch_participant(board.id, board.candidate.id, at=now_ms() - 10_000)

        response = client.post(
            f"/sessions/{board.id}/participants/{board.candidate.id}/heartbeat",
            headers=board.candidate.headers,
        )

        assert response.status_code == 204
        refreshed = store.find_participant(board.id, board.candidate.id)
        assert now_ms() - refreshed.last_seen < 1_000

    def test_is_a_no_op_for_an_unknown_participant(self, client: TestClient, board) -> None:
        response = client.post(
            f"/sessions/{board.id}/participants/p_doesnotexist/heartbeat",
            headers=board.candidate.headers,
        )

        assert response.status_code == 204

    def test_keeps_working_after_being_removed(self, client: TestClient, board) -> None:
        """A client that beats on after removal must not 401-loop."""
        client.delete(
            f"/sessions/{board.id}/participants/{board.candidate.id}",
            headers=board.interviewer.headers,
        )

        response = client.post(
            f"/sessions/{board.id}/participants/{board.candidate.id}/heartbeat",
            headers=board.candidate.headers,
        )

        assert response.status_code == 204
        assert store.find_participant(board.id, board.candidate.id) is None, "not resurrected"

    def test_requires_a_token(self, client: TestClient, board) -> None:
        response = client.post(
            f"/sessions/{board.id}/participants/{board.candidate.id}/heartbeat"
        )

        assert response.status_code == 401


class TestRemove:
    def test_self_leave_removes_participant_and_cursor(self, client: TestClient, board) -> None:
        client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json={
                "participantId": board.candidate.id,
                "name": board.candidate.name,
                "color": board.candidate.color,
                "x": 10,
                "y": 20,
                "at": now_ms(),
            },
            headers=board.candidate.headers,
        )

        response = client.delete(
            f"/sessions/{board.id}/participants/{board.candidate.id}",
            headers=board.candidate.headers,
        )

        assert response.status_code == 204
        roster = client.get(
            f"/sessions/{board.id}/participants", headers=board.interviewer.headers
        ).json()
        cursors = client.get(
            f"/sessions/{board.id}/cursors", headers=board.interviewer.headers
        ).json()
        assert board.candidate.id not in [p["id"] for p in roster]
        assert board.candidate.id not in [c["participantId"] for c in cursors]

    def test_the_host_can_remove_anyone(self, client: TestClient, board) -> None:
        response = client.delete(
            f"/sessions/{board.id}/participants/{board.observer.id}",
            headers=board.interviewer.headers,
        )

        assert response.status_code == 204

    def test_a_candidate_cannot_remove_someone_else(self, client: TestClient, board) -> None:
        response = client.delete(
            f"/sessions/{board.id}/participants/{board.observer.id}",
            headers=board.candidate.headers,
        )

        assert response.status_code == 403
        assert response.json()["error"] == "forbidden_role"
        assert store.find_participant(board.id, board.observer.id) is not None

    def test_is_idempotent_for_an_unknown_id(self, client: TestClient, board) -> None:
        response = client.delete(
            f"/sessions/{board.id}/participants/p_doesnotexist",
            headers=board.interviewer.headers,
        )

        assert response.status_code == 204

    def test_repeated_self_leave_stays_204(self, client: TestClient, board) -> None:
        """`beforeunload` and the Leave button can both fire."""
        path = f"/sessions/{board.id}/participants/{board.candidate.id}"

        first = client.delete(path, headers=board.candidate.headers)
        second = client.delete(path, headers=board.candidate.headers)

        assert first.status_code == second.status_code == 204


class TestLeaveBeacon:
    def test_accepts_the_token_in_the_body(self, client: TestClient, board) -> None:
        """`navigator.sendBeacon` can only POST, and cannot set headers."""
        response = client.post(
            f"/sessions/{board.id}/participants/{board.candidate.id}/leave",
            json={"token": board.candidate.token},
        )

        assert response.status_code == 204
        assert store.find_participant(board.id, board.candidate.id) is None

    def test_accepts_a_bare_token_body(self, client: TestClient, board) -> None:
        response = client.post(
            f"/sessions/{board.id}/participants/{board.candidate.id}/leave",
            content=board.candidate.token,
            headers={"Content-Type": "text/plain"},
        )

        assert response.status_code == 204

    def test_accepts_the_authorization_header_too(self, client: TestClient, board) -> None:
        response = client.post(
            f"/sessions/{board.id}/participants/{board.candidate.id}/leave",
            headers=board.candidate.headers,
        )

        assert response.status_code == 204

    def test_without_a_token_it_is_401(self, client: TestClient, board) -> None:
        response = client.post(
            f"/sessions/{board.id}/participants/{board.candidate.id}/leave"
        )

        assert response.status_code == 401
        assert store.find_participant(board.id, board.candidate.id) is not None

    def test_cannot_remove_someone_else(self, client: TestClient, board) -> None:
        response = client.post(
            f"/sessions/{board.id}/participants/{board.observer.id}/leave",
            json={"token": board.candidate.token},
        )

        assert response.status_code == 403


class TestRemovedParticipantLosesAccess:
    def test_reads_are_rejected_after_removal(self, client: TestClient, board) -> None:
        client.delete(
            f"/sessions/{board.id}/participants/{board.candidate.id}",
            headers=board.interviewer.headers,
        )

        response = client.get(f"/sessions/{board.id}/canvas", headers=board.candidate.headers)

        assert response.status_code == 401
