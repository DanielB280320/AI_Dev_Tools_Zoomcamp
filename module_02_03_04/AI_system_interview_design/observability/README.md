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
make obs-up      # or: docker compose -f observability/docker-compose.yaml up -d --wait
make api-obs     # the API, sending here, with metrics every 5 s
make web         # the frontend, to do something worth measuring
```

For the app running in Docker instead (`make up`), the Collector is on the host,
not on the app's network:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4318 make up
```

Then open http://localhost:3000. You're signed in as an admin automatically.

**The Loopboard dashboard** (http://localhost:3000/d/loopboard-product, in the
*Loopboard* folder) shows what people do with the app. It refreshes every 5
seconds:

| Panel | Metric (`backend/app/metrics.py`) | Moves when |
| --- | --- | --- |
| Interview rooms created | `loopboard_sessions_created_total` | someone creates a room (the demo seed doesn't count) |
| People in interviews now | `loopboard_participants_active` | someone joins a live room, or stops heartbeating for 15 s, or the room ends |
| Elements created | `loopboard_canvas_elements_created_total` | a shape, arrow, stroke or text is added; edits and moves don't count |

Below the totals are the same three over time, split by participant role and
by element type. The *Environment* selector filters on
`deployment_environment_name`. An action shows up within about 10 seconds: one
5-second export interval plus one refresh. With plain `make api`, which keeps
the SDK's 60-second default interval, it takes up to a minute.

Dashboards are files in `grafana/dashboards/`. To change one, edit it in
Grafana, export the JSON over the file, and Grafana reloads it within 30
seconds.

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

**Alerts:** two rules ("Canvas writes failing", "API returning server errors")
are provisioned from `grafana/provisioning/alerting/rules.yaml`, under
*Alerting ▸ Alert rules*. To see one fire, run the API with
`LOOPBOARD_FAULT_ELEMENT_FAILURE_RATE=0.5` and add elements to a board
([deploy/README.md, "Testing an alert"](../deploy/README.md#testing-an-alert)).

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
- **Deployed:** the same files run on their own EC2 instance for dev and prod,
  with a Grafana login and HTTPS through CloudFront
  (`docker-compose.deploy.yaml`; [deploy/README.md, "Observability"](../deploy/README.md#observability)).
- **This file's defaults are for a laptop, not a public address.** Grafana runs with anonymous admin
  access and no login form. Every UI port is bound to 127.0.0.1. Only OTLP
  listens on all interfaces, because an app container reaches it through
  `host.docker.internal`, and on Linux that's the Docker bridge, not loopback.
- **Every counter series starts at 0.** Prometheus's `increase()` can't see an
  increment on a series' first sample, so without that the first room after a
  restart would never show up.
