"""OpenTelemetry: traces and metrics, exported over OTLP/HTTP.

Off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. With no collector running, an
exporter pointed at its default `localhost:4318` would log a failed export
every few seconds for the life of the process, so the absence of an endpoint
means "not configured", not "use the default".

Set, it is the base URL (`https://otlp.example.com`, or `http://localhost:4318`
for a local Jaeger or Grafana); the exporters append `/v1/traces` and
`/v1/metrics` themselves. Everything else an OTLP exporter reads from the
environment works unchanged — `OTEL_EXPORTER_OTLP_HEADERS` for a vendor's API
key, `OTEL_TRACES_SAMPLER` for sampling, `OTEL_METRIC_EXPORT_INTERVAL` — except
the protocol, which is http/protobuf whatever `OTEL_EXPORTER_OTLP_PROTOCOL`
says, since that is the only exporter installed.

Every span and metric carries the resource below, so any one of them answers
"which service, which environment, which build":

* `service.name` — `OTEL_SERVICE_NAME`, else `loopboard-api`.
* `service.version` — the package version.
* `deployment.environment.name` — `LOOPBOARD_ENV` (`dev`, `prod`), else `local`.
* `vcs.ref.head.revision` — `LOOPBOARD_GIT_COMMIT`, the commit the image was
  built from. The Dockerfile bakes it in, so a promoted image reports the
  commit it was built from on every environment it runs in. Absent when
  unknown, rather than a placeholder that would group unrelated builds.

What is instrumented: every HTTP request (a server span plus the
`http.server.*` duration metrics) and every SQL statement (a child span plus
the pool's connection-usage metric). `/health` is left out — the compose
health check calls it every three seconds and its spans would be most of the
traffic — and a request is one span, not one per ASGI message, which on an
SSE stream would be a span per event.
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from . import __version__
from .config import settings

#: Requests not traced, as the instrumentation's comma-separated regexes.
EXCLUDED_URLS = "/health$"


def build_resource() -> Resource:
    """The attributes stamped on every span and metric this process exports.

    `Resource.create` also folds in `OTEL_RESOURCE_ATTRIBUTES`, so a deployment
    can add its own (a host, a region) without a code change; the ones set here
    win over it.
    """
    attributes: dict[str, str] = {
        "service.name": settings.service_name,
        "service.version": __version__,
        "deployment.environment.name": settings.environment,
    }
    if settings.git_commit:
        attributes["vcs.ref.head.revision"] = settings.git_commit
    return Resource.create(attributes)


def setup_telemetry(
    app: FastAPI,
    *,
    span_processor: SpanProcessor | None = None,
    metric_reader: MetricReader | None = None,
) -> bool:
    """Instrument `app` and the database, if an OTLP endpoint is configured.

    The processor and reader are for the tests, which pass in-memory ones; given
    either, telemetry is on regardless of the endpoint. Returns whether it is.

    The providers become the process-wide ones, so a span started anywhere with
    `trace.get_tracer(__name__)` is exported along with the instrumentation's.
    SQLAlchemy is instrumented by wrapping `sqlalchemy.create_engine`, which is
    why this has to run before the first engine is built — it does, since
    `app.db` builds the engine lazily, on the first request or at startup.
    """
    if not (settings.otlp_endpoint or span_processor or metric_reader):
        return False

    resource = build_resource()

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor or BatchSpanProcessor(OTLPSpanExporter()))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader or PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=EXCLUDED_URLS,
        # One span per ASGI message otherwise: an SSE stream sends a chunk per
        # event and per keepalive, each of which would be a span of its own.
        exclude_spans=["receive", "send"],
    )
    SQLAlchemyInstrumentor().instrument(
        tracer_provider=tracer_provider, meter_provider=meter_provider
    )
    return True
