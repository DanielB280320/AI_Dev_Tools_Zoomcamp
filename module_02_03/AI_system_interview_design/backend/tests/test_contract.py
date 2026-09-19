"""Conformance with ../openapi.yaml: every operation, and the schema shapes.

These tests read the contract file itself, so drifting from it fails the suite
rather than being discovered by the frontend.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import models
from app.main import app
from app.seed import URL_SHORTENER_ID

CONTRACT = yaml.safe_load((Path(__file__).parents[2] / "openapi.yaml").read_text())
IMPLEMENTED = app.openapi()

METHODS = {"get", "put", "post", "delete", "patch"}

#: Operations this backend adds on top of the contract. `openapi.yaml` declares
#: `interviewerAuth` but no operation that issues such a token ("Gap to close"),
#: so sign-in had to be invented. The `leave` alias is specified in the contract's
#: prose (for `navigator.sendBeacon`) but has no path entry of its own, and
#: `/health` is for probes.
ADDITIONS = {
    ("/auth/register", "post"),
    ("/auth/login", "post"),
    ("/auth/logout", "post"),
    ("/auth/me", "get"),
    ("/sessions/{sessionId}/participants/{participantId}/leave", "post"),
    ("/health", "get"),
}


def contract_operations() -> list[tuple[str, str]]:
    return [
        (path, method)
        for path, item in CONTRACT["paths"].items()
        for method in item
        if method in METHODS
    ]


def implemented_operations() -> set[tuple[str, str]]:
    return {
        (path, method)
        for path, item in IMPLEMENTED["paths"].items()
        for method in item
        if method in METHODS
    }


@pytest.mark.parametrize(("path", "method"), contract_operations())
def test_every_contract_operation_is_implemented(path: str, method: str) -> None:
    assert (path, method) in implemented_operations()


def test_the_only_extra_operations_are_the_documented_additions() -> None:
    extra = implemented_operations() - set(contract_operations())

    assert extra == ADDITIONS


def test_operation_ids_match_the_contract() -> None:
    """A generated client keys off `operationId`, so each one is set explicitly."""
    for path, method in contract_operations():
        expected = CONTRACT["paths"][path][method]["operationId"]

        assert IMPLEMENTED["paths"][path][method]["operationId"] == expected


REQUIRED_FIELD_MODELS = {
    "Session": models.Session,
    "CreateSessionRequest": models.CreateSessionRequest,
    "Participant": models.Participant,
    "JoinSessionRequest": models.JoinSessionRequest,
    "CursorState": models.CursorState,
    "CanvasDoc": models.CanvasDoc,
    "ShapeNode": models.ShapeNode,
    "ArrowNode": models.ArrowNode,
    "StrokeNode": models.StrokeNode,
    "TextNode": models.TextNode,
    "Error": models.Error,
}


@pytest.mark.parametrize(("name", "model"), sorted(REQUIRED_FIELD_MODELS.items()))
def test_required_fields_match_the_contract(name: str, model: type) -> None:
    declared = set(CONTRACT["components"]["schemas"][name]["required"])
    fields = {
        (field.alias or field_name)
        for field_name, field in model.model_fields.items()
        if field.is_required() or field_name == "type"
    }

    assert declared <= fields, f"{name} is missing {sorted(declared - fields)}"


@pytest.mark.parametrize(
    ("name", "model"),
    [("Session", models.Session), ("Participant", models.Participant), ("CursorState", models.CursorState)],
)
def test_no_properties_beyond_the_contract(name: str, model: type) -> None:
    """These objects are declared `additionalProperties: false`."""
    allowed = set(CONTRACT["components"]["schemas"][name]["properties"])
    actual = {(field.alias or field_name) for field_name, field in model.model_fields.items()}

    assert actual == allowed


def test_enums_match_the_contract() -> None:
    schemas = CONTRACT["components"]["schemas"]

    assert [role.value for role in models.Role] == schemas["Role"]["enum"]
    assert [status.value for status in models.SessionStatus] == schemas["SessionStatus"]["enum"]
    assert sorted(kind.value for kind in models.ComponentKind) == sorted(
        schemas["ComponentKind"]["enum"]
    )


def test_both_security_schemes_are_declared(client: TestClient) -> None:
    schemes = IMPLEMENTED["components"]["securitySchemes"]

    assert set(schemes) == {"participantAuth", "interviewerAuth"}
    assert all(scheme["scheme"] == "bearer" for scheme in schemes.values())


def test_public_operations_stay_public() -> None:
    """Reading a session and joining it must need no credentials."""
    for path, method in (("/sessions/{sessionId}", "get"), ("/sessions/{sessionId}/participants", "post")):
        operation = IMPLEMENTED["paths"][path][method]

        assert "security" not in operation or operation["security"] == []


def test_generated_schema_is_servable(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_health_reports_the_seeded_store(client: TestClient) -> None:
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["sessions"] == 5


class TestCors:
    """The browser calls this API cross-origin from the Vite dev server."""

    FRONTEND_ORIGIN = "http://localhost:8080"

    def test_the_frontend_dev_origin_is_allowed(self, client: TestClient) -> None:
        response = client.get(f"/sessions/{URL_SHORTENER_ID}", headers={"Origin": self.FRONTEND_ORIGIN})

        assert response.headers["access-control-allow-origin"] == self.FRONTEND_ORIGIN

    def test_preflight_permits_the_authorization_header(self, client: TestClient) -> None:
        response = client.options(
            f"/sessions/{URL_SHORTENER_ID}/canvas",
            headers={
                "Origin": self.FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

        assert response.status_code == 200
        assert "authorization" in response.headers["access-control-allow-headers"].lower()

    def test_an_unknown_origin_gets_no_allowance(self, client: TestClient) -> None:
        response = client.get(
            f"/sessions/{URL_SHORTENER_ID}", headers={"Origin": "http://evil.example"}
        )

        assert "access-control-allow-origin" not in response.headers
