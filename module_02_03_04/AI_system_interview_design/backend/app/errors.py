"""The single error shape the contract specifies: `{"error": code, "message": ...}`.

FastAPI's default is `{"detail": ...}`, so every failure path goes through
`ApiError` and the handlers registered in `main.create_app`.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse


class ApiError(Exception):
    """An error with a stable machine-readable code, rendered as `Error`."""

    def __init__(
        self,
        status_code: int,
        error: str,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"{status_code} {error}")
        self.status_code = status_code
        self.error = error
        self.message = message
        self.headers = headers

    def response(self) -> JSONResponse:
        body: dict[str, str] = {"error": self.error}
        if self.message:
            body["message"] = self.message
        return JSONResponse(body, status_code=self.status_code, headers=self.headers)


def unauthorized(message: str = "Missing, malformed or expired bearer token.") -> ApiError:
    return ApiError(401, "unauthorized", message, headers={"WWW-Authenticate": "Bearer"})


def forbidden(error: str = "forbidden", message: str | None = None) -> ApiError:
    return ApiError(403, error, message)


def session_not_found(session_id: str) -> ApiError:
    return ApiError(404, "session_not_found", f"No session with id {session_id!r}.")


def canvas_locked(message: str = "The session is ended or the canvas is locked.") -> ApiError:
    return ApiError(409, "canvas_locked", message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return exc.response()

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return ApiError(400, "invalid_request", _describe(exc)).response()

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}
        error = codes.get(exc.status_code, "error")
        detail = exc.detail if isinstance(exc.detail, str) else None
        return ApiError(exc.status_code, error, detail, headers=exc.headers).response()


def _describe(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(piece) for piece in err.get("loc", ()) if piece != "body")
        parts.append(f"{loc or 'body'}: {err.get('msg', 'invalid')}")
    return "; ".join(parts) or "Malformed request body."
