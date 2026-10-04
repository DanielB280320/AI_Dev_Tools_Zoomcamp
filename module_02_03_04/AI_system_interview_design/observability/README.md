# Observability stack

Where the backend's OpenTelemetry goes (`backend/app/telemetry.py`). It's a
Compose project of its own (`loopboard-observability`), separate from the app
stack, so each one starts, stops and wipes without touching the other.

```
app ──OTLP──▶ otel-collector ──┬─ traces  ─▶ Tempo      ─┐
   (:4318)                     ├─ metrics ─▶ Prometheus ─┼─▶ Grafana (:3000)
                               └─ logs    ─▶ Loki       ─┘
```

| Service | Image | Host port | Role |
| --- | --- | --- | --- |
| otel-collector | `otel/opentelemetry-collector-contrib:0.161.0` | 4317 (gRPC), 4318 (HTTP) | The single OTLP endpoint; batches and retries |
| prometheus | `prom/prometheus:v3.15.0` | 127.0.0.1:9090 | Metrics, received as OTLP pushes |
| loki | `grafana/loki:3.7.8` | 127.0.0.1:3100 | Logs, received as OTLP |
| tempo | `grafana/tempo:3.1.0` | 127.0.0.1:3200 | Traces |
| grafana | `grafana/grafana:13.2.3` | 127.0.0.1:3000 | UI; datasources provisioned and linked |

## Use it

```bash
make obs-up                                            # or: docker compose -f observability/docker-compose.yaml up -d --wait
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 make api
```

For the app running in Docker instead (`make up`), the Collector is on the host,
not on the app's network:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318 make up
```

Then open http://localhost:3000. You're signed in as an admin automatically.
In **Explore**:

- **Tempo**: `{resource.service.name="loopboard-api"}`. Each request is a trace
  with its SQL statements nested under it. *Logs for this span* and *Request
  rate* jump to Loki and Prometheus.
- **Prometheus**: `http_server_duration_milliseconds_count`. Environment and
  commit are ordinary labels (`deployment_environment_name`,
  `vcs_ref_head_revision`). Turn on *Exemplars* to jump from a latency point to
  a trace that produced it.
- **Loki**: `{service_name="loopboard-api"}`. The backend doesn't export logs
  yet, so this stays empty until it does. The pipeline is already in place.

`make obs-logs` follows the Collector's log. It prints a line for each batch it
receives, which is the quickest way to check whether the app is reaching it.
`make obs-down` stops the stack and keeps the data;
`docker compose -f observability/docker-compose.yaml down -v` wipes it.

## Design notes

- **OTLP end to end.** Prometheus (`--web.enable-otlp-receiver`), Loki (`/otlp`)
  and Tempo all take OTLP natively, so the Collector forwards and doesn't
  convert anything. The resource attributes the app sets (service, environment,
  commit) arrive unchanged in all three.
- **Resource attributes become labels.** Prometheus promotes `service.version`,
  `deployment.environment.name` and `vcs.ref.head.revision`. Loki indexes
  `deployment.environment.name` alongside its defaults. Either way you can
  filter by environment or build without joining against `target_info`.
- **Retention:** 7 days for Prometheus and Loki, and Tempo's default of 14 days.
- **For a laptop, not a public address.** Grafana runs with anonymous admin
  access and no login form. Every UI port is bound to 127.0.0.1. Only OTLP
  listens on all interfaces, because an app container reaches it through
  `host.docker.internal`, and on Linux that's the Docker bridge, not loopback.
- **No dashboards yet.** Datasources are provisioned; dashboards can go in
  `grafana/provisioning/dashboards/` (and a matching mount) once there's
  something worth keeping.
