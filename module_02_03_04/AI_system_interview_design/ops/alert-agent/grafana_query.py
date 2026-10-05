#!/usr/bin/env python3
"""Read-only Grafana queries for the alert agent's Claude session.

    grafana_query.py prom   '<promql>'   [--minutes 60]
    grafana_query.py logs   '<logql>'    [--minutes 60] [--limit 100]
    grafana_query.py traces '<traceql>'  [--limit 20]
    grafana_query.py trace  <trace id>

Uses GRAFANA_URL and GRAFANA_TOKEN (a Viewer token) from the environment, which
watch.py sets for the session. One fixed tool rather than hand-built curl
commands, because its permissions can be granted exactly: it only ever reads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def request(path: str, body: dict | None = None, **params: str) -> dict:
    url = os.environ["GRAFANA_URL"].rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"content-type": "application/json"})
    req.add_header("Authorization", f"Bearer {os.environ['GRAFANA_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def prom(expr: str, minutes: int) -> None:
    body = {
        "queries": [{"refId": "A", "datasource": {"uid": "prometheus"}, "expr": expr, "instant": True}],
        "from": f"now-{minutes}m",
        "to": "now",
    }
    frames = request("/api/ds/query", body)["results"]["A"].get("frames", [])
    if not frames:
        print("(no data)")
    for frame in frames:
        labels = frame["schema"]["fields"][1].get("labels", {})
        print(f"{labels} = {frame['data']['values'][1][-1]}")


def logs(logql: str, minutes: int, limit: int) -> None:
    end = time.time_ns()
    result = request(
        "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
        query=logql, start=str(end - minutes * 60 * 10**9), end=str(end), limit=str(limit),
    )
    streams = result.get("data", {}).get("result", [])
    if not streams:
        print("(no log lines)")
    for stream in streams:
        print(f"## {stream['stream']}")
        for _ts, line in stream["values"]:
            print(line)


def traces(traceql: str, limit: int) -> None:
    result = request("/api/datasources/proxy/uid/tempo/api/search", q=traceql, limit=str(limit))
    print(json.dumps(result.get("traces", []), indent=2))


def trace(trace_id: str) -> None:
    print(json.dumps(request(f"/api/datasources/proxy/uid/tempo/api/v2/traces/{trace_id}"), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="kind", required=True)
    p = sub.add_parser("prom")
    p.add_argument("expr")
    p.add_argument("--minutes", type=int, default=60)
    p = sub.add_parser("logs")
    p.add_argument("logql")
    p.add_argument("--minutes", type=int, default=60)
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("traces")
    p.add_argument("traceql")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("trace")
    p.add_argument("trace_id")
    args = parser.parse_args()
    try:
        if args.kind == "prom":
            prom(args.expr, args.minutes)
        elif args.kind == "logs":
            logs(args.logql, args.minutes, args.limit)
        elif args.kind == "traces":
            traces(args.traceql, args.limit)
        else:
            trace(args.trace_id)
    except urllib.error.HTTPError as error:
        sys.exit(f"Grafana answered {error.code}: {error.read().decode()[:500]}")


if __name__ == "__main__":
    main()
