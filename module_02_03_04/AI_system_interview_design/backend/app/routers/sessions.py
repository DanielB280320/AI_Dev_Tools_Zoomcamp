"""Session lifecycle — create, list, read, end, reopen, delete."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ..auth import CurrentInterviewer, SessionCaller, SessionIdPath, require_host
from ..errors import forbidden, session_not_found
from ..events import broker
from ..models import CreateSessionRequest, Session
from ..store import store
from ._responses import errors

router = APIRouter(tags=["Sessions"])


@router.post(
    "/sessions",
    operation_id="createSession",
    status_code=status.HTTP_201_CREATED,
    summary="Create an interview session",
    responses=errors(400, 401),
)
async def create_session(body: CreateSessionRequest, account: CurrentInterviewer) -> Session:
    """Starts a `live` session with an empty canvas, no participants, no cursors.

    Empty `title` / `hostName` fall back to "Untitled interview" / "Interviewer".
    """
    record = store.create_session(account.id, body.title, body.hostName)
    return record.to_model()


@router.get(
    "/sessions",
    operation_id="listSessions",
    summary="List the calling interviewer's sessions, newest first",
    responses=errors(401),
)
async def list_sessions(account: CurrentInterviewer) -> list[Session]:
    """Sorted by `createdAt` descending — the dashboard renders the array as-is."""
    return [record.to_model() for record in store.list_sessions(account.id)]


@router.get(
    "/sessions/{sessionId}",
    operation_id="getSession",
    summary="Read a session",
    responses=errors(404),
)
async def get_session(sessionId: SessionIdPath) -> Session:
    """Public: the join page calls this before the visitor has any identity."""
    record = store.get_session(sessionId)
    if record is None:
        raise session_not_found(sessionId)
    return record.to_model()


@router.delete(
    "/sessions/{sessionId}",
    operation_id="deleteSession",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session and everything in it",
    responses=errors(401, 403),
)
async def delete_session(sessionId: SessionIdPath, account: CurrentInterviewer) -> Response:
    """Host-only and idempotent: deleting an already-deleted session is still 204."""
    record = store.get_session(sessionId)
    if record is not None:
        if record.owner_id != account.id:
            raise forbidden("not_session_owner", "Only the owning interviewer can delete this.")
        store.delete_session(sessionId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{sessionId}/end",
    operation_id="endSession",
    summary="End a session (freeze the board)",
    responses=errors(401, 403, 404),
)
async def end_session(caller: SessionCaller) -> Session:
    """Sets `status: ended`, `endedAt`, `canvasLocked: true`. Emits `session`."""
    record = store.end_session(require_host(caller).session)
    broker.publish(record.id, "session")
    return record.to_model()


@router.post(
    "/sessions/{sessionId}/reopen",
    operation_id="reopenSession",
    summary="Reopen an ended session",
    responses=errors(401, 403, 404),
)
async def reopen_session(caller: SessionCaller) -> Session:
    """Inverse of end: `live`, `endedAt: null`, `canvasLocked: false`. Emits `session`."""
    record = store.reopen_session(require_host(caller).session)
    broker.publish(record.id, "session")
    return record.to_model()
