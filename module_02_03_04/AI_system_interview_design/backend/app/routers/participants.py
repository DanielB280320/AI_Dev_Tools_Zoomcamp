"""Join / leave, the presence roster, and heartbeats."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request, Response, status

from ..auth import (
    Credentials,
    LenientSessionCaller,
    ParticipantIdPath,
    SessionAccess,
    SessionCaller,
    SessionIdPath,
    authorize_session,
    bearer_token,
)
from ..errors import forbidden, session_not_found
from ..events import broker
from ..models import JoinSessionRequest, JoinSessionResponse, Participant
from ..store import store
from ._responses import errors

router = APIRouter(prefix="/sessions/{sessionId}/participants", tags=["Participants"])


@router.post(
    "",
    operation_id="joinSession",
    status_code=status.HTTP_201_CREATED,
    summary="Join a session",
    responses=errors(400, 404),
)
async def join_session(sessionId: SessionIdPath, body: JoinSessionRequest) -> JoinSessionResponse:
    """Public — no account needed.

    Assigns the next palette colour by join order and returns the participant
    plus its `participantAuth` token. Joining an `ended` session is allowed: the
    participant simply gets read-only access to the frozen board. Emits
    `presence`.
    """
    if store.get_session(sessionId) is None:
        raise session_not_found(sessionId)
    participant, token = store.join(sessionId, body.name, body.role)
    broker.publish(sessionId, "presence")
    return JoinSessionResponse(**participant.to_model().model_dump(), token=token)


@router.get(
    "",
    operation_id="listParticipants",
    summary="List participants currently in the session",
    responses=errors(401, 403, 404),
)
async def list_participants(caller: SessionCaller) -> list[Participant]:
    """Join order, with participants whose heartbeat went stale dropped."""
    return [p.to_model() for p in store.list_participants(caller.session.id)]


@router.delete(
    "/{participantId}",
    operation_id="removeParticipant",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave the session, or remove another participant",
    responses=errors(401, 403),
)
async def remove_participant(
    caller: LenientSessionCaller, participantId: ParticipantIdPath
) -> Response:
    """Self-leave, or the host removing someone.

    Removes the participant and their cursor, then emits `presence`. Idempotent:
    an unknown participant id is still a 204.
    """
    _remove(caller, participantId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{participantId}/leave",
    operation_id="leaveSession",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Leave the session (sendBeacon-friendly alias)",
    description=(
        "Identical semantics to `DELETE`, as a `POST` so the frontend can use "
        "`navigator.sendBeacon` from its `beforeunload` handler. Because a beacon cannot set "
        "headers, the participant token may travel in the body as `{\"token\": \"...\"}` "
        "instead of in `Authorization`."
    ),
    responses=errors(401, 403),
)
async def leave_session(
    sessionId: SessionIdPath,
    participantId: ParticipantIdPath,
    request: Request,
    credentials: Credentials,
) -> Response:
    raw_token = bearer_token(credentials) or await _token_from_body(request)
    caller = authorize_session(sessionId, raw_token, require_membership=False)
    _remove(caller, participantId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{participantId}/heartbeat",
    operation_id="heartbeat",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a participant as still present",
    responses=errors(401),
)
async def heartbeat(caller: LenientSessionCaller, participantId: ParticipantIdPath) -> Response:
    """Refreshes `lastSeen`. Deliberately cheap, and emits **no** event — every
    open board calls this every 4 s.

    A no-op (still 204) for an unknown participant id, so a client that kept
    beating after being removed does not error-loop.
    """
    store.touch_participant(caller.session.id, participantId)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _remove(caller: SessionAccess, participant_id: str) -> None:
    """Callers may remove themselves; the host may remove anyone."""
    if not caller.is_host and caller.principal.participant_id != participant_id:
        raise forbidden("forbidden_role", "Only the interviewer can remove another participant.")
    if store.remove_participant(caller.session.id, participant_id):
        broker.publish(caller.session.id, "presence")


async def _token_from_body(request: Request) -> str | None:
    """Pull the token out of a beacon body, which may arrive as JSON or bare text."""
    raw = (await request.body()).strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        text = raw.decode("utf-8", "replace").strip()
        return text or None
    if isinstance(parsed, dict):
        token = parsed.get("token")
        return token if isinstance(token, str) and token else None
    return parsed if isinstance(parsed, str) and parsed else None
