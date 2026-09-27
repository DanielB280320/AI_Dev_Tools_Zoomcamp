"""The canvas document: whole-document writes, node operations, locks and roles."""

from __future__ import annotations

from conftest import RATE_LIMITER_ID, URL_SHORTENER_ID, auth, join, update_row
from fastapi.testclient import TestClient

from app import tables
from app.config import settings


def shape(node_id: str, author: str, x: float = 0, y: float = 0, label: str = "Service") -> dict:
    return {
        "type": "shape",
        "id": node_id,
        "kind": "service",
        "label": label,
        "x": x,
        "y": y,
        "w": 160,
        "h": 80,
        "authorId": author,
    }


def arrow(node_id: str, author: str, src: str = "n_one", dst: str = "n_two") -> dict:
    return {
        "type": "arrow",
        "id": node_id,
        "from": {"shapeId": src},
        "to": {"shapeId": dst},
        "label": "writes to",
        "dashed": True,
        "bidirectional": False,
        "authorId": author,
    }


def every_node_type(author: str) -> list[dict]:
    return [
        shape("n_shape", author),
        arrow("n_arrow", author, "n_shape", "n_shape"),
        {
            "type": "arrow",
            "id": "n_pinned",
            "from": {"x": -12.5, "y": 40},
            "to": {"shapeId": "n_shape"},
            "label": "",
            "dashed": False,
            "bidirectional": True,
            "authorId": author,
        },
        {
            "type": "stroke",
            "id": "n_stroke",
            "points": [[120, 340], [122, 344], [127.5, 351]],
            "color": "#f5b83d",
            "width": 3,
            "authorId": author,
        },
        {"type": "text", "id": "n_text", "x": 10, "y": 20, "text": "", "authorId": author},
    ]


class TestRead:
    def test_an_empty_board_is_an_empty_node_list(self, client: TestClient, board) -> None:
        response = client.get(f"/sessions/{board.id}/canvas", headers=board.candidate.headers)

        assert response.status_code == 200
        assert response.json() == {"nodes": []}

    def test_observers_can_read(self, client: TestClient, board) -> None:
        assert (
            client.get(f"/sessions/{board.id}/canvas", headers=board.observer.headers).status_code
            == 200
        )

    def test_unknown_session_is_404(self, client: TestClient, board) -> None:
        response = client.get("/sessions/nosuchsessionid/canvas", headers=board.candidate.headers)

        assert response.status_code == 404

    def test_requires_a_token(self, client: TestClient, board) -> None:
        assert client.get(f"/sessions/{board.id}/canvas").status_code == 401

    def test_seeded_board_round_trips_unchanged(self, client: TestClient) -> None:
        member = join(client, URL_SHORTENER_ID, "Reader", "observer")

        body = client.get(f"/sessions/{URL_SHORTENER_ID}/canvas", headers=member.headers).json()

        kinds = {node["type"] for node in body["nodes"]}
        assert kinds == {"shape", "arrow", "stroke", "text"}, "the seed exercises every node type"
        assert any("from" in node and "x" in node["from"] for node in body["nodes"]), (
            "and a point-anchored arrow endpoint"
        )


class TestWholeDocumentWrite:
    def test_round_trips_every_node_type(self, client: TestClient, board) -> None:
        nodes = every_node_type(board.candidate.id)

        saved = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": nodes}, headers=board.candidate.headers
        )

        assert saved.status_code == 204
        body = client.get(f"/sessions/{board.id}/canvas", headers=board.candidate.headers).json()
        assert body == {"nodes": nodes}, "the `from` alias survives the round trip"

    def test_array_order_is_preserved_because_it_is_z_order(
        self, client: TestClient, board
    ) -> None:
        nodes = [shape(f"n_{index}", board.candidate.id) for index in range(5)]
        client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": nodes}, headers=board.candidate.headers
        )

        body = client.get(f"/sessions/{board.id}/canvas", headers=board.candidate.headers).json()

        assert [node["id"] for node in body["nodes"]] == [node["id"] for node in nodes]

    def test_replaces_rather_than_merges(self, client: TestClient, board) -> None:
        client.put(
            f"/sessions/{board.id}/canvas",
            json={"nodes": [shape("n_old", board.candidate.id)]},
            headers=board.candidate.headers,
        )

        client.put(
            f"/sessions/{board.id}/canvas",
            json={"nodes": [shape("n_new", board.candidate.id)]},
            headers=board.candidate.headers,
        )

        body = client.get(f"/sessions/{board.id}/canvas", headers=board.candidate.headers).json()
        assert [node["id"] for node in body["nodes"]] == ["n_new"]

    def test_the_owning_interviewer_account_can_write(self, client: TestClient, board) -> None:
        response = client.put(
            f"/sessions/{board.id}/canvas",
            json={"nodes": [shape("n_host", "p_host")]},
            headers=auth(board.host_token),
        )

        assert response.status_code == 204


class TestWriteRules:
    def test_observers_are_forbidden(self, client: TestClient, board) -> None:
        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=board.observer.headers
        )

        assert response.status_code == 403
        assert response.json()["error"] == "forbidden_role"

    def test_an_ended_session_rejects_writes(self, client: TestClient, board) -> None:
        client.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=board.candidate.headers
        )

        assert response.status_code == 409
        assert response.json()["error"] == "canvas_locked"

    def test_reopening_restores_writes(self, client: TestClient, board) -> None:
        client.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)
        client.post(f"/sessions/{board.id}/reopen", headers=board.interviewer.headers)

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=board.candidate.headers
        )

        assert response.status_code == 204

    def test_a_locked_live_board_rejects_writes(self, client: TestClient, board) -> None:
        """`canvasLocked` freezes the board independently of `status`."""
        update_row(tables.SessionRecord, board.id, canvas_locked=True)

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=board.candidate.headers
        )

        assert response.status_code == 409

    def test_every_write_path_honours_the_lock(self, client: TestClient, board) -> None:
        client.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)
        headers = board.candidate.headers

        assert (
            client.patch(
                f"/sessions/{board.id}/canvas/nodes", json={"nodes": []}, headers=headers
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/sessions/{board.id}/canvas/nodes/delete", json={"ids": []}, headers=headers
            ).status_code
            == 409
        )

    def test_the_seeded_ended_board_is_read_only(self, client: TestClient) -> None:
        member = join(client, RATE_LIMITER_ID, "Reviewer", "candidate")

        read = client.get(f"/sessions/{RATE_LIMITER_ID}/canvas", headers=member.headers)
        write = client.put(
            f"/sessions/{RATE_LIMITER_ID}/canvas", json={"nodes": []}, headers=member.headers
        )

        assert read.status_code == 200 and len(read.json()["nodes"]) > 0
        assert write.status_code == 409


class TestValidation:
    def test_unknown_node_type_is_rejected(self, client: TestClient, board) -> None:
        response = client.put(
            f"/sessions/{board.id}/canvas",
            json={"nodes": [{"type": "sticky", "id": "n_x"}]},
            headers=board.candidate.headers,
        )

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"

    def test_unknown_component_kind_is_rejected(self, client: TestClient, board) -> None:
        node = shape("n_x", board.candidate.id) | {"kind": "blockchain"}

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": [node]}, headers=board.candidate.headers
        )

        assert response.status_code == 400

    def test_extra_keys_are_rejected(self, client: TestClient, board) -> None:
        node = shape("n_x", board.candidate.id) | {"rotation": 45}

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": [node]}, headers=board.candidate.headers
        )

        assert response.status_code == 400

    def test_a_stroke_point_must_be_a_pair(self, client: TestClient, board) -> None:
        node = {
            "type": "stroke",
            "id": "n_s",
            "points": [[1, 2, 3]],
            "color": "#fff",
            "width": 2,
            "authorId": board.candidate.id,
        }

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": [node]}, headers=board.candidate.headers
        )

        assert response.status_code == 400

    def test_an_endpoint_must_be_a_shape_or_a_point(self, client: TestClient, board) -> None:
        node = arrow("n_a", board.candidate.id) | {"from": {"shapeId": "n_one", "x": 3}}

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": [node]}, headers=board.candidate.headers
        )

        assert response.status_code == 400

    def test_too_many_nodes_is_413(self, client: TestClient, board, monkeypatch) -> None:
        monkeypatch.setattr(settings, "max_canvas_nodes", 3)
        nodes = [shape(f"n_{index}", board.candidate.id) for index in range(4)]

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": nodes}, headers=board.candidate.headers
        )

        assert response.status_code == 413
        assert response.json()["error"] == "canvas_too_large"

    def test_too_many_bytes_is_413(self, client: TestClient, board, monkeypatch) -> None:
        monkeypatch.setattr(settings, "max_canvas_bytes", 200)
        nodes = [shape(f"n_{index}", board.candidate.id) for index in range(10)]

        response = client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": nodes}, headers=board.candidate.headers
        )

        assert response.status_code == 413


class TestNodeOperations:
    def test_upsert_appends_new_nodes_and_replaces_in_place(
        self, client: TestClient, board
    ) -> None:
        headers = board.candidate.headers
        client.put(
            f"/sessions/{board.id}/canvas",
            json={"nodes": [shape("n_a", board.candidate.id), shape("n_b", board.candidate.id)]},
            headers=headers,
        )

        response = client.patch(
            f"/sessions/{board.id}/canvas/nodes",
            json={
                "nodes": [
                    shape("n_a", board.candidate.id, x=500, label="Auth Service"),
                    shape("n_c", board.candidate.id),
                ]
            },
            headers=headers,
        )

        assert response.status_code == 204
        nodes = client.get(f"/sessions/{board.id}/canvas", headers=headers).json()["nodes"]
        assert [node["id"] for node in nodes] == ["n_a", "n_b", "n_c"], "z-order is not disturbed"
        assert nodes[0]["label"] == "Auth Service"
        assert nodes[0]["x"] == 500

    def test_upsert_accepts_client_generated_ids_verbatim(self, client: TestClient, board) -> None:
        client_id = "n_4k2mq7xr9b"

        client.patch(
            f"/sessions/{board.id}/canvas/nodes",
            json={"nodes": [shape(client_id, board.candidate.id)]},
            headers=board.candidate.headers,
        )

        nodes = client.get(
            f"/sessions/{board.id}/canvas", headers=board.candidate.headers
        ).json()["nodes"]
        assert [node["id"] for node in nodes] == [client_id]

    def test_delete_removes_listed_ids_and_ignores_unknown_ones(
        self, client: TestClient, board
    ) -> None:
        headers = board.candidate.headers
        client.put(
            f"/sessions/{board.id}/canvas",
            json={"nodes": [shape(f"n_{index}", board.candidate.id) for index in range(3)]},
            headers=headers,
        )

        response = client.post(
            f"/sessions/{board.id}/canvas/nodes/delete",
            json={"ids": ["n_0", "n_2", "n_nonexistent"]},
            headers=headers,
        )

        assert response.status_code == 204
        nodes = client.get(f"/sessions/{board.id}/canvas", headers=headers).json()["nodes"]
        assert [node["id"] for node in nodes] == ["n_1"]

    def test_deleting_a_shape_keeps_arrows_anchored_to_it(
        self, client: TestClient, board
    ) -> None:
        """Cascading is a product decision, not part of this contract."""
        headers = board.candidate.headers
        client.put(
            f"/sessions/{board.id}/canvas",
            json={
                "nodes": [
                    shape("n_shape", board.candidate.id),
                    arrow("n_arrow", board.candidate.id, "n_shape", "n_shape"),
                ]
            },
            headers=headers,
        )

        client.post(
            f"/sessions/{board.id}/canvas/nodes/delete", json={"ids": ["n_shape"]}, headers=headers
        )

        nodes = client.get(f"/sessions/{board.id}/canvas", headers=headers).json()["nodes"]
        assert [node["id"] for node in nodes] == ["n_arrow"]

    def test_observers_cannot_use_the_node_operations(self, client: TestClient, board) -> None:
        patched = client.patch(
            f"/sessions/{board.id}/canvas/nodes",
            json={"nodes": [shape("n_x", board.observer.id)]},
            headers=board.observer.headers,
        )
        deleted = client.post(
            f"/sessions/{board.id}/canvas/nodes/delete",
            json={"ids": ["n_x"]},
            headers=board.observer.headers,
        )

        assert patched.status_code == deleted.status_code == 403

    def test_upsert_respects_the_node_budget_against_the_existing_document(
        self, client: TestClient, board, monkeypatch
    ) -> None:
        headers = board.candidate.headers
        client.put(
            f"/sessions/{board.id}/canvas",
            json={"nodes": [shape(f"n_{index}", board.candidate.id) for index in range(3)]},
            headers=headers,
        )
        monkeypatch.setattr(settings, "max_canvas_nodes", 3)

        response = client.patch(
            f"/sessions/{board.id}/canvas/nodes",
            json={"nodes": [shape("n_extra", board.candidate.id)]},
            headers=headers,
        )

        assert response.status_code == 413
