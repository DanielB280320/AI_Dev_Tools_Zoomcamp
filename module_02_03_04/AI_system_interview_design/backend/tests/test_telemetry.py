"""OpenTelemetry wiring: the resource, and what a request exports.

The app under test in the rest of the suite runs with telemetry off (no OTLP
endpoint), so these build their own app with in-memory exporters in place of
OTLP ones.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import __version__
from app.config import settings
from app.db import dispose_engine
from app.main import create_app
from app.telemetry import build_resource, setup_telemetry


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings as a prod deployment of one commit would have them."""
    monkeypatch.setattr(settings, "service_name", "loopboard-api")
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "git_commit", "83242da0c0ffee")


def test_resource_names_service_environment_and_commit(deployed: None) -> None:
    attributes = build_resource().attributes
    assert attributes["service.name"] == "loopboard-api"
    assert attributes["service.version"] == __version__
    assert attributes["deployment.environment.name"] == "prod"
    assert attributes["vcs.ref.head.revision"] == "83242da0c0ffee"


def test_resource_omits_an_unknown_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "git_commit", "")
    assert "vcs.ref.head.revision" not in build_resource().attributes


def test_off_without_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "otlp_endpoint", "")
    assert setup_telemetry(create_app()) is False


@pytest.fixture
def exported(
    deployed: None,
) -> Iterator[tuple[TestClient, InMemorySpanExporter, InMemoryMetricReader]]:
    """An instrumented app, and where its spans and metrics land.

    The engine is rebuilt on both sides: inside, so it is created through the
    instrumented `create_engine`; after, so the rest of the suite gets a plain one.
    """
    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    app = create_app()
    assert setup_telemetry(app, span_processor=SimpleSpanProcessor(spans), metric_reader=reader)
    dispose_engine()
    try:
        with TestClient(app) as client:
            yield client, spans, reader
    finally:
        SQLAlchemyInstrumentor().uninstrument()
        dispose_engine()


def test_a_request_exports_a_server_span_with_sql_children(
    client: TestClient, exported: tuple[TestClient, InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    instrumented, spans, _ = exported
    spans.clear()  # startup's own statements

    assert instrumented.get("/sessions/does-not-exist").status_code in {401, 404}

    finished = spans.get_finished_spans()
    server = [span for span in finished if span.kind.name == "SERVER"]
    assert len(server) == 1
    assert server[0].resource.attributes["deployment.environment.name"] == "prod"
    assert server[0].resource.attributes["vcs.ref.head.revision"] == "83242da0c0ffee"

    trace_id = server[0].context.trace_id
    sql = [
        span
        for span in finished
        if span.kind.name == "CLIENT" and "db.statement" in span.attributes
    ]
    assert sql, [span.name for span in finished]
    assert all(span.context.trace_id == trace_id for span in sql)


def test_health_is_not_traced(
    client: TestClient, exported: tuple[TestClient, InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    instrumented, spans, _ = exported
    spans.clear()
    assert instrumented.get("/health").status_code == 200
    assert not [span for span in spans.get_finished_spans() if span.kind.name == "SERVER"]


def test_a_request_records_http_metrics(
    client: TestClient, exported: tuple[TestClient, InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    instrumented, _, reader = exported
    instrumented.get("/sessions/does-not-exist")

    data = reader.get_metrics_data()
    names = {
        metric.name
        for resource_metrics in data.resource_metrics
        for scope in resource_metrics.scope_metrics
        for metric in scope.metrics
    }
    assert any(name.startswith("http.server.") for name in names), names
    assert data.resource_metrics[0].resource.attributes["service.name"] == "loopboard-api"


def test_a_request_is_one_span_not_one_per_message(
    client: TestClient, exported: tuple[TestClient, InMemorySpanExporter, InMemoryMetricReader]
) -> None:
    instrumented, spans, _ = exported
    spans.clear()
    instrumented.get("/sessions/does-not-exist")
    names = [span.name for span in spans.get_finished_spans()]
    assert not [name for name in names if name.endswith((" http send", " http receive"))], names
