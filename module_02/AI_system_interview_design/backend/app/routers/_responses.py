"""Shared OpenAPI response declarations, so `/docs` matches openapi.yaml."""

from __future__ import annotations

from typing import Any

from ..models import Error

_DESCRIPTIONS = {
    400: "Malformed body or failed validation.",
    401: "Missing, malformed or expired token.",
    403: "Authenticated but not permitted.",
    404: "No such session (or it was deleted).",
    409: "The session is ended or the canvas is locked, so writes are rejected.",
    413: "Document exceeds the server's size limit.",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": Error, "description": _DESCRIPTIONS[code]} for code in codes}
