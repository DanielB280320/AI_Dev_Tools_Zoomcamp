"""Authentication and authorisation.

Two bearer schemes, exactly as the contract describes them:

* `interviewerAuth` — account-scoped, obtained from `POST /auth/login`.
* `participantAuth` — session-scoped, issued by the join endpoint. Opaque to
  the client; the session id, participant id and role live in the server-side
  token record.

Passwords are stored as salted PBKDF2-HMAC-SHA256 digests. Verification is a
constant-time compare, and a login against an unknown email still pays the
hashing cost so the response time does not reveal which emails exist.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .errors import canvas_locked, forbidden, session_not_found, unauthorized
from .models import Role
from .store import Account, SessionRecord, TokenRecord, store

HASH_SCHEME = "pbkdf2_sha256"
SALT_BYTES = 16


def hash_password(password: str, *, iterations: int | None = None) -> str:
    """`pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>`."""
    rounds = iterations or settings.pbkdf2_iterations
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"{HASH_SCHEME}${rounds}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_b64, digest_b64 = encoded.split("$")
        if scheme != HASH_SCHEME:
            return False
        expected = _unb64(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt_b64), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


#: A throwaway hash used to keep failed logins as slow as successful ones.
_DUMMY_HASH: str | None = None


def waste_hash_time(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("password-that-is-never-valid")
    verify_password(password, _DUMMY_HASH)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


# ------------------------------- dependencies -------------------------------

interviewer_scheme = HTTPBearer(
    scheme_name="interviewerAuth",
    auto_error=False,
    description="Account-scoped token from POST /auth/login.",
)

participant_scheme = HTTPBearer(
    scheme_name="participantAuth",
    auto_error=False,
    description="Session-scoped token from POST /sessions/{sessionId}/participants.",
)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(participant_scheme)]
InterviewerCredentials = Annotated[
    HTTPAuthorizationCredentials | None, Depends(interviewer_scheme)
]
# No `minLength` guard here even though the contract declares one: a short,
# bogus link should get the 404 the frontend renders as "this link isn't valid",
# not a validation error.
SessionIdPath = Annotated[str, Path(alias="sessionId", max_length=64)]
ParticipantIdPath = Annotated[str, Path(alias="participantId", max_length=64)]


@dataclass(frozen=True)
class Principal:
    """Who is calling, resolved from a bearer token."""

    kind: Literal["interviewer", "participant"]
    token: TokenRecord
    account: Account | None = None

    @property
    def session_id(self) -> str | None:
        return self.token.session_id

    @property
    def participant_id(self) -> str | None:
        return self.token.participant_id

    @property
    def role(self) -> Role | None:
        return self.token.role


def resolve_token(raw: str | None) -> Principal:
    if not raw:
        raise unauthorized()
    record = store.token(raw)
    if record is None:
        raise unauthorized()
    if record.kind == "interviewer":
        account = store.get_account(record.account_id)
        if account is None:
            raise unauthorized("The account behind this token no longer exists.")
        return Principal(kind="interviewer", token=record, account=account)
    return Principal(kind="participant", token=record)


def bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


async def current_interviewer(credentials: InterviewerCredentials) -> Account:
    """`interviewerAuth`: the dashboard operations that are not session-scoped."""
    principal = resolve_token(bearer_token(credentials))
    if principal.kind != "interviewer" or principal.account is None:
        raise unauthorized("This operation needs an interviewer token.")
    return principal.account


CurrentInterviewer = Annotated[Account, Depends(current_interviewer)]


@dataclass(frozen=True)
class SessionAccess:
    """An authenticated caller together with the session they addressed."""

    session: SessionRecord
    principal: Principal

    @property
    def is_host(self) -> bool:
        """Host = `participantAuth` with role interviewer, or the owning account."""
        if self.principal.kind == "interviewer":
            account = self.principal.account
            return account is not None and self.session.owner_id == account.id
        return self.principal.role is Role.interviewer

    @property
    def is_observer(self) -> bool:
        return self.principal.role is Role.observer


def authorize_session(
    session_id: str, raw_token: str | None, *, require_membership: bool = True
) -> SessionAccess:
    """Authenticate (401), then check the session exists (404), then scope (403).

    `require_membership=False` is for the operations the contract wants to stay
    quiet for a participant who has already left or been pruned — leave and
    heartbeat — so a client that kept calling gets a 204, not a 401 loop.
    """
    principal = resolve_token(raw_token)
    session = store.get_session(session_id)
    if session is None:
        raise session_not_found(session_id)
    if principal.kind == "participant":
        if principal.session_id != session_id:
            raise forbidden("wrong_session", "This token belongs to a different session.")
        on_roster = store.find_participant(session_id, principal.participant_id or "")
        if require_membership and on_roster is None:
            raise unauthorized("This participant is no longer in the session.")
    elif principal.account is None or session.owner_id != principal.account.id:
        raise forbidden("not_session_owner", "This interviewer does not own the session.")
    return SessionAccess(session=session, principal=principal)


async def session_access(
    sessionId: SessionIdPath,
    credentials: Credentials,
) -> SessionAccess:
    return authorize_session(sessionId, bearer_token(credentials))


SessionCaller = Annotated[SessionAccess, Depends(session_access)]


async def lenient_session_access(
    sessionId: SessionIdPath,
    credentials: Credentials,
) -> SessionAccess:
    """For leave / heartbeat: a participant already off the roster still passes."""
    return authorize_session(sessionId, bearer_token(credentials), require_membership=False)


LenientSessionCaller = Annotated[SessionAccess, Depends(lenient_session_access)]


async def sse_session_access(
    sessionId: SessionIdPath,
    credentials: Credentials,
    token: Annotated[
        str | None,
        Query(description="Token alternative to the Authorization header, for EventSource."),
    ] = None,
) -> SessionAccess:
    """`EventSource` cannot set headers, so the stream also takes `?token=`."""
    return authorize_session(sessionId, bearer_token(credentials) or token)


SseSessionCaller = Annotated[SessionAccess, Depends(sse_session_access)]


def require_host(access: SessionAccess) -> SessionAccess:
    if not access.is_host:
        raise forbidden("forbidden_role", "Only the interviewer can do this.")
    return access


def require_editor(access: SessionAccess) -> SessionAccess:
    """Canvas writes: observers are rejected, and a frozen board rejects everyone."""
    if access.is_observer:
        raise forbidden("forbidden_role", "Observers have read-only access.")
    if store.writes_blocked(access.session):
        raise canvas_locked()
    return access
