"""Change notifications: which mutation emits what, and the SSE wire format."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest
import uvicorn
from conftest import auth
from fastapi.testclient import TestClient

from app.config import settings
from app.events import EventBroker, broker, format_event
from app.main import app
from app.store import now_ms


@pytest.fixture
def live_server(client: TestClient):
    """A real server on a random port, so streaming responses actually stream."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "the test server did not come up"
    port = server.servers[0].sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def keepalive_fast(monkeypatch):
    monkeypatch.setattr(settings, "sse_keepalive_seconds", 0.05)


@pytest.fixture
def emitted(monkeypatch) -> list[tuple[str, str]]:
    """Records every `broker.publish` call as `(session_id, kind)`."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        broker,
        "publish",
        lambda session_id, kind, **_: calls.append((session_id, kind)),
    )
    return calls


@pytest.fixture
def excluded(monkeypatch) -> list[str | None]:
    """Records the `exclude_participant` of every `broker.publish` call."""
    skipped: list[str | None] = []
    monkeypatch.setattr(
        broker,
        "publish",
        lambda _session_id, _kind, *, exclude_participant=None: skipped.append(
            exclude_participant
        ),
    )
    return skipped


class TestEventMatrix:
    def test_canvas_writes_emit_doc(self, client: TestClient, board, emitted) -> None:
        headers = board.candidate.headers
        node = {
            "type": "text",
            "id": "n_t",
            "x": 0,
            "y": 0,
            "text": "hi",
            "authorId": board.candidate.id,
        }

        client.put(f"/sessions/{board.id}/canvas", json={"nodes": [node]}, headers=headers)
        client.patch(f"/sessions/{board.id}/canvas/nodes", json={"nodes": [node]}, headers=headers)
        client.post(
            f"/sessions/{board.id}/canvas/nodes/delete", json={"ids": ["n_t"]}, headers=headers
        )

        assert emitted == [(board.id, "doc")] * 3

    def test_join_leave_and_cursors_emit_presence(
        self, client: TestClient, board, emitted
    ) -> None:
        from conftest import join

        member = join(client, board.id, "Late", "candidate")
        client.put(
            f"/sessions/{board.id}/cursors/{member.id}",
            json={
                "participantId": member.id,
                "name": member.name,
                "color": member.color,
                "x": 1,
                "y": 2,
                "at": now_ms(),
            },
            headers=member.headers,
        )
        client.delete(f"/sessions/{board.id}/participants/{member.id}", headers=member.headers)

        assert emitted == [(board.id, "presence")] * 3

    def test_end_and_reopen_emit_session(self, client: TestClient, board, emitted) -> None:
        client.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)
        client.post(f"/sessions/{board.id}/reopen", headers=board.interviewer.headers)

        assert emitted == [(board.id, "session"), (board.id, "session")]

    def test_heartbeats_are_silent(self, client: TestClient, board, emitted) -> None:
        """Four beats a second per participant must not wake every subscriber."""
        for _ in range(3):
            client.post(
                f"/sessions/{board.id}/participants/{board.candidate.id}/heartbeat",
                headers=board.candidate.headers,
            )

        assert emitted == []

    def test_reads_and_session_creation_are_silent(
        self, client: TestClient, board, emitted
    ) -> None:
        client.get(f"/sessions/{board.id}/canvas", headers=board.candidate.headers)
        client.get(f"/sessions/{board.id}/participants", headers=board.candidate.headers)
        client.get(f"/sessions/{board.id}/cursors", headers=board.candidate.headers)
        client.post("/sessions", json={"title": "T", "hostName": "H"}, headers=auth(board.host_token))

        assert emitted == []

    def test_a_failed_write_emits_nothing(self, client: TestClient, board, emitted) -> None:
        client.put(f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=board.observer.headers)

        assert emitted == []


class TestWriterExclusion:
    """The contract asks for `doc` to skip the writer, which spares every client
    a re-fetch of its own 120 ms-debounced save."""

    def test_canvas_writes_skip_the_writer(self, client: TestClient, board, excluded) -> None:
        headers = board.candidate.headers

        client.put(f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=headers)
        client.patch(f"/sessions/{board.id}/canvas/nodes", json={"nodes": []}, headers=headers)
        client.post(
            f"/sessions/{board.id}/canvas/nodes/delete", json={"ids": []}, headers=headers
        )

        assert excluded == [board.candidate.id] * 3

    def test_cursor_publishes_skip_the_publisher(self, client: TestClient, board, excluded) -> None:
        client.put(
            f"/sessions/{board.id}/cursors/{board.candidate.id}",
            json={
                "participantId": board.candidate.id,
                "name": board.candidate.name,
                "color": board.candidate.color,
                "x": 1,
                "y": 2,
                "at": now_ms(),
            },
            headers=board.candidate.headers,
        )

        assert excluded == [board.candidate.id]

    def test_presence_and_session_changes_reach_everyone(
        self, client: TestClient, board, excluded
    ) -> None:
        """A host ending the session, or removing someone, must see it too."""
        client.delete(
            f"/sessions/{board.id}/participants/{board.observer.id}",
            headers=board.interviewer.headers,
        )
        client.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)

        assert excluded == [None, None]

    def test_an_interviewer_account_write_excludes_nobody(
        self, client: TestClient, board, excluded
    ) -> None:
        """An account token has no participant id, so there is no stream to skip."""
        client.put(
            f"/sessions/{board.id}/canvas", json={"nodes": []}, headers=auth(board.host_token)
        )

        assert excluded == [None]

    def test_the_excluded_subscriber_gets_nothing_while_others_do(self) -> None:
        async def scenario() -> tuple[str, bool]:
            bus = EventBroker()
            writer = bus.stream("s", "p_writer")
            watcher = bus.stream("s", "p_watcher")
            await anext(writer)
            await anext(watcher)

            bus.publish("s", "doc", exclude_participant="p_writer")
            delivered = await asyncio.wait_for(anext(watcher), timeout=2)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(anext(writer), timeout=0.2)

            await writer.aclose()
            await watcher.aclose()
            return delivered, True

        delivered, _ = asyncio.run(scenario())
        assert delivered == format_event("doc", "s")


class TestBroker:
    def test_frame_format(self) -> None:
        assert format_event("doc", "abc") == 'event: doc\ndata: {"sessionId":"abc"}\n\n'

    def test_delivers_only_to_the_right_session(self) -> None:
        async def scenario() -> list[str]:
            bus = EventBroker()
            stream = bus.stream("wanted")
            assert await anext(stream) == ": connected\n\n"

            bus.publish("other", "doc")
            bus.publish("wanted", "presence")
            frame = await asyncio.wait_for(anext(stream), timeout=2)
            await stream.aclose()
            return [frame]

        assert asyncio.run(scenario()) == [format_event("presence", "wanted")]

    def test_fans_out_to_every_subscriber(self) -> None:
        async def scenario() -> tuple[str, str]:
            bus = EventBroker()
            first, second = bus.stream("s"), bus.stream("s")
            await anext(first)
            await anext(second)
            assert bus.subscriber_count("s") == 2

            bus.publish("s", "doc")
            frames = (
                await asyncio.wait_for(anext(first), timeout=2),
                await asyncio.wait_for(anext(second), timeout=2),
            )
            await first.aclose()
            await second.aclose()
            assert bus.subscriber_count("s") == 0, "subscribers are cleaned up on disconnect"
            return frames

        assert asyncio.run(scenario()) == (format_event("doc", "s"),) * 2

    def test_a_slow_subscriber_drops_the_oldest_event(self, monkeypatch) -> None:
        """Losing a notification costs one extra fetch, never an edit."""
        monkeypatch.setattr("app.events.QUEUE_SIZE", 2)

        async def scenario() -> list[str]:
            bus = EventBroker()
            stream = bus.stream("s")
            await anext(stream)

            for kind in ("doc", "presence", "session"):
                bus.publish("s", kind)

            frames = [
                await asyncio.wait_for(anext(stream), timeout=2),
                await asyncio.wait_for(anext(stream), timeout=2),
            ]
            await stream.aclose()
            return frames

        assert asyncio.run(scenario()) == [
            format_event("presence", "s"),
            format_event("session", "s"),
        ]

    def test_sends_a_keepalive_when_idle(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "sse_keepalive_seconds", 0.01)

        async def scenario() -> str:
            bus = EventBroker()
            stream = bus.stream("s")
            await anext(stream)
            frame = await asyncio.wait_for(anext(stream), timeout=2)
            await stream.aclose()
            return frame

        assert asyncio.run(scenario()) == ": keepalive\n\n"


class TestSseEndpoint:
    """Driven against a real uvicorn server: `httpx`'s ASGI transport buffers the
    whole response, which an endless stream never finishes."""

    def test_stream_carries_a_real_canvas_write(self, live_server: str, board) -> None:
        """End to end: one client subscribes, another writes, `doc` arrives.

        The subscriber is the observer and the writer the candidate, because a
        writer is deliberately skipped by its own `doc` event.
        """
        with httpx.Client(base_url=live_server, timeout=5) as http, http.stream(
            "GET", f"/sessions/{board.id}/events", headers=board.observer.headers
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-cache, no-transform"
            assert response.headers["x-accel-buffering"] == "no"

            lines = response.iter_lines()
            assert _read_frame(lines) == [": connected"]

            written = http.put(
                f"/sessions/{board.id}/canvas",
                json={"nodes": []},
                headers=board.candidate.headers,
            )
            assert written.status_code == 204

            assert _read_frame(lines) == [
                "event: doc",
                f'data: {{"sessionId":"{board.id}"}}',
            ]

    def test_presence_and_session_events_reach_the_stream(
        self, live_server: str, board
    ) -> None:
        with httpx.Client(base_url=live_server, timeout=5) as http, http.stream(
            "GET", f"/sessions/{board.id}/events", headers=board.observer.headers
        ) as response:
            lines = response.iter_lines()
            _read_frame(lines)

            http.post(
                f"/sessions/{board.id}/participants",
                json={"name": "Late", "role": "candidate"},
            )
            assert _read_frame(lines)[0] == "event: presence"

            http.post(f"/sessions/{board.id}/end", headers=board.interviewer.headers)
            assert _read_frame(lines)[0] == "event: session"

    def test_keepalives_hold_the_connection_open(
        self, live_server: str, board, keepalive_fast
    ) -> None:
        with httpx.Client(base_url=live_server, timeout=5) as http, http.stream(
            "GET", f"/sessions/{board.id}/events", headers=board.candidate.headers
        ) as response:
            lines = response.iter_lines()
            _read_frame(lines)

            assert _read_frame(lines) == [": keepalive"]

    def test_accepts_a_token_query_parameter(self, live_server: str, board) -> None:
        """`EventSource` cannot set an Authorization header."""
        with httpx.Client(base_url=live_server, timeout=5) as http, http.stream(
            "GET", f"/sessions/{board.id}/events?token={board.candidate.token}"
        ) as response:
            assert response.status_code == 200
            assert _read_frame(response.iter_lines()) == [": connected"]

    def test_disconnecting_unsubscribes(self, live_server: str, board) -> None:
        with httpx.Client(base_url=live_server, timeout=5) as http, http.stream(
            "GET", f"/sessions/{board.id}/events", headers=board.candidate.headers
        ) as response:
            _read_frame(response.iter_lines())
            assert broker.subscriber_count(board.id) == 1

        deadline = time.monotonic() + 5
        while broker.subscriber_count(board.id) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert broker.subscriber_count(board.id) == 0

    def test_rejects_a_missing_or_foreign_token(self, client: TestClient, board) -> None:
        anonymous = client.get(f"/sessions/{board.id}/events")
        unknown_session = client.get(
            "/sessions/nosuchsessionid/events", headers=board.candidate.headers
        )

        assert anonymous.status_code == 401
        assert unknown_session.status_code == 404


def _read_frame(lines) -> list[str]:
    """Collect one SSE frame — the lines up to the blank separator."""
    frame: list[str] = []
    for line in lines:
        if line == "":
            return frame
        frame.append(line)
    raise AssertionError("the stream closed mid-frame")
