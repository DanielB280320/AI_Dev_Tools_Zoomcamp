"""Live cursor positions, published per participant and polled per session."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ..auth import ParticipantIdPath, SessionCaller
from ..errors import forbidden
from ..events import broker
from ..models import CursorState
from ..store import store
from ._responses import errors

router = APIRouter(prefix="/sessions/{sessionId}/cursors", tags=["Cursors"])


@router.get("", operation_id="listCursors", summary="List live cursors", responses=errors(401, 403, 404))
async def list_cursors(caller: SessionCaller) -> list[CursorState]:
    """Only cursors published in the last 15 s; the server owns that filtering.

    The caller's own cursor may be included — the frontend filters it out by
    `participantId`.
    """
    return store.list_cursors(caller.session.id)


@router.put(
    "/{participantId}",
    operation_id="publishCursor",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Publish this participant's cursor position",
    responses=errors(400, 401, 403),
)
async def publish_cursor(
    caller: SessionCaller, participantId: ParticipantIdPath, body: CursorState
) -> Response:
    """Upsert, in canvas space (unbounded, may be negative). Emits `presence`.

    Callers may only publish their own cursor: both the path id and the body's
    `participantId` must match the token.
    """
    own = caller.principal.participant_id
    if own is None or participantId != own or body.participantId != own:
        raise forbidden("forbidden_cursor", "A participant may only publish its own cursor.")
    store.put_cursor(caller.session.id, body)
    # The publisher draws its own pointer locally; only the others need waking.
    broker.publish(caller.session.id, "presence", exclude_participant=own)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
