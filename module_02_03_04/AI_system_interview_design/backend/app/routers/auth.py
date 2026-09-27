"""Interviewer sign-in — the "gap to close" noted in the contract.

openapi.yaml defines `interviewerAuth` but no way to obtain such a token,
because the frontend has no sign-in screen yet. These operations are the
minimum needed to make the dashboard endpoints usable; they are an addition to
the contract, not a change to any operation in it.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from ..auth import (
    CurrentInterviewer,
    InterviewerCredentials,
    bearer_token,
    hash_password,
    verify_password,
    waste_hash_time,
)
from ..errors import ApiError, unauthorized
from ..models import (
    AuthTokenResponse,
    Error,
    InterviewerAccount,
    LoginRequest,
    RegisterRequest,
)
from ..store import Account, store
from ._responses import errors

router = APIRouter(prefix="/auth", tags=["Auth"])


def _public(account: Account) -> InterviewerAccount:
    return InterviewerAccount(id=account.id, email=account.email, name=account.name)


def _issue(account: Account) -> AuthTokenResponse:
    return AuthTokenResponse(
        token=store.issue_interviewer_token(account.id), interviewer=_public(account)
    )


@router.post(
    "/register",
    operation_id="registerInterviewer",
    status_code=status.HTTP_201_CREATED,
    summary="Create an interviewer account",
    responses={
        **errors(400),
        409: {"model": Error, "description": "An account with that email already exists."},
    },
)
async def register(body: RegisterRequest) -> AuthTokenResponse:
    """Registers the account and signs it in, so the dashboard can go straight in."""
    email = body.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ApiError(400, "invalid_email", "Provide a valid email address.")
    if store.account_by_email(email) is not None:
        raise ApiError(409, "email_taken", "An account with that email already exists.")
    account = store.create_account(email, body.name, hash_password(body.password))
    return _issue(account)


@router.post(
    "/login",
    operation_id="loginInterviewer",
    summary="Sign in and receive an interviewerAuth token",
    responses=errors(400, 401),
)
async def login(body: LoginRequest) -> AuthTokenResponse:
    account = store.account_by_email(body.email)
    if account is None:
        # Hash anyway: equal timing for known and unknown emails.
        waste_hash_time(body.password)
        raise unauthorized("Email or password is incorrect.")
    if not verify_password(body.password, account.password_hash):
        raise unauthorized("Email or password is incorrect.")
    return _issue(account)


@router.get("/me", operation_id="getCurrentInterviewer", summary="The signed-in interviewer", responses=errors(401))
async def me(account: CurrentInterviewer) -> InterviewerAccount:
    return _public(account)


@router.post(
    "/logout",
    operation_id="logoutInterviewer",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the calling interviewer token",
    responses=errors(401),
)
async def logout(account: CurrentInterviewer, credentials: InterviewerCredentials) -> None:
    raw = bearer_token(credentials)
    if raw:
        store.revoke_token(raw)
