"""Server-Sent Events — the replacement for the frontend's BroadcastChannel."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..auth import SseSessionCaller
from ..events import broker
from ._responses import errors

router = APIRouter(tags=["Realtime"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Tell nginx not to buffer the stream; without it events arrive in batches.
    "X-Accel-Buffering": "no",
}


@router.get(
    "/sessions/{sessionId}/events",
    operation_id="subscribeToSession",
    summary="Subscribe to session change notifications (SSE)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "An open event stream.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
        **errors(401, 403, 404),
    },
)
async def subscribe_to_session(caller: SseSessionCaller) -> StreamingResponse:
    """Three event names only — `doc`, `presence`, `session`.

    The payload is just `{"sessionId": "..."}`: events are change
    notifications, and the client re-fetches the affected resource. A
    `: keepalive` comment goes out every ~20 s so proxies hold the connection
    open.

    `EventSource` cannot set an `Authorization` header, so the token may also be
    passed as `?token=...`.
    """
    return StreamingResponse(
        broker.stream(caller.session.id, caller.principal.participant_id),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
