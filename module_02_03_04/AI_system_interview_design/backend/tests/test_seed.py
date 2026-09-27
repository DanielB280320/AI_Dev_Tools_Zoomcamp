"""The demo data: it has to be valid, coherent, and useful to the frontend."""

from __future__ import annotations

import pytest
from conftest import ALEX, SAM, auth, join, login
from fastapi.testclient import TestClient

from app.config import settings
from app.models import CanvasDoc
from app.seed import (
    CHAT_SYSTEM_ID,
    DEMO_PASSWORD,
    EMPTY_BOARD_ID,
    OTHER_OWNER_ID,
    RATE_LIMITER_ID,
    URL_SHORTENER_ID,
)
from app.store import PALETTE, now_ms, store

ALL_IDS = [URL_SHORTENER_ID, CHAT_SYSTEM_ID, RATE_LIMITER_ID, EMPTY_BOARD_ID, OTHER_OWNER_ID]


def test_every_demo_session_exists(client: TestClient) -> None:
    for session_id in ALL_IDS:
        assert client.get(f"/sessions/{session_id}").status_code == 200


def test_both_demo_accounts_can_sign_in(client: TestClient) -> None:
    for email in (ALEX, SAM):
        response = client.post("/auth/login", json={"email": email, "password": DEMO_PASSWORD})

        assert response.status_code == 200


def test_the_dashboard_has_a_mix_to_render(client: TestClient) -> None:
    body = client.get("/sessions", headers=auth(login(client))).json()

    assert len(body) == 4, "Sam's board is not Alex's"
    assert [session["createdAt"] for session in body] == sorted(
        (session["createdAt"] for session in body), reverse=True
    )
    assert {session["status"] for session in body} == {"live", "ended"}


def test_the_empty_board_shows_the_string_fallbacks(client: TestClient) -> None:
    body = client.get(f"/sessions/{EMPTY_BOARD_ID}").json()

    assert body["title"] == "Untitled interview"
    assert body["hostName"] == "Interviewer"
    assert store.get_doc(EMPTY_BOARD_ID) == []


@pytest.mark.parametrize("session_id", ALL_IDS)
def test_documents_validate_against_the_canvas_schema(client: TestClient, session_id: str) -> None:
    doc = CanvasDoc(nodes=store.get_doc(session_id))

    assert doc.model_dump(by_alias=True)["nodes"] == [
        node.model_dump(by_alias=True) for node in store.get_doc(session_id)
    ]


@pytest.mark.parametrize("session_id", ALL_IDS)
def test_node_ids_are_unique_within_a_document(client: TestClient, session_id: str) -> None:
    ids = [node.id for node in store.get_doc(session_id)]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("session_id", ALL_IDS)
def test_anchored_arrows_point_at_shapes_that_exist(client: TestClient, session_id: str) -> None:
    nodes = store.get_doc(session_id)
    shape_ids = {node.id for node in nodes if node.type == "shape"}

    for arrow in (node for node in nodes if node.type == "arrow"):
        for endpoint in (arrow.from_, arrow.to):
            shape_id = getattr(endpoint, "shapeId", None)
            assert shape_id is None or shape_id in shape_ids, f"dangling anchor in {session_id}"


def test_participants_are_fresh_and_coloured_from_the_palette(client: TestClient) -> None:
    member = join(client, URL_SHORTENER_ID, "Inspector", "observer")

    roster = client.get(
        f"/sessions/{URL_SHORTENER_ID}/participants", headers=member.headers
    ).json()

    assert len(roster) == 4
    assert [p["color"] for p in roster] == list(PALETTE[:4]), "colours follow join order"
    for participant in roster:
        assert now_ms() - participant["lastSeen"] < settings.participant_ttl_ms


def test_the_busy_board_has_something_on_it(client: TestClient) -> None:
    member = join(client, URL_SHORTENER_ID, "Inspector", "observer")

    nodes = client.get(f"/sessions/{URL_SHORTENER_ID}/canvas", headers=member.headers).json()[
        "nodes"
    ]

    assert len(nodes) > 15
    assert {node["type"] for node in nodes} == {"shape", "arrow", "stroke", "text"}


def test_authors_on_the_live_boards_are_real_participants(client: TestClient) -> None:
    for session_id in (URL_SHORTENER_ID, CHAT_SYSTEM_ID):
        roster = {p.id for p in store.list_participants(session_id)}

        authors = {node.authorId for node in store.get_doc(session_id)}
        assert authors <= roster, f"{session_id} has nodes by a phantom author"


def test_sessions_are_isolated_per_owner(client: TestClient) -> None:
    sam_ids = {s["id"] for s in client.get("/sessions", headers=auth(login(client, SAM))).json()}

    assert sam_ids == {OTHER_OWNER_ID}
