#!/usr/bin/env python3
"""Watch Loopboard's Grafana alerts; on a firing one, start a headless Claude
Code session that diagnoses it and proposes a fix.

    python3 ops/alert-agent/watch.py              # poll until stopped (make alert-agent)
    python3 ops/alert-agent/watch.py --once       # one poll, then exit
    python3 ops/alert-agent/watch.py --dry-run    # gather evidence and write the prompt, no Claude

What the session may do is decided here, not by the prompt (README.md,
"Boundaries"): it gets no AWS credentials at all — this script collects the
prod evidence itself, with fixed read-only commands, before it starts — a
Grafana Viewer token, and a fresh git worktree off origin/main whose only
allowed push target is an `alert-agent/...` branch.

Standard library only, so it runs on any Python 3.11+ with no install.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent.parent  # module_02_03_04/AI_system_interview_design
REPO_ROOT = Path(
    subprocess.run(
        ["git", "-C", str(APP_DIR), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)
APP_PATH = APP_DIR.relative_to(REPO_ROOT)

STATE_DIR = Path(os.environ.get("ALERT_AGENT_HOME", Path.home() / ".local/state/loopboard-alert-agent"))
OBS_STACK = "loopboard-observability"
TOKEN_PARAMETER = f"/{OBS_STACK}/alert-agent-grafana-token"
#: deployment.environment.name -> the app stack that runs it (deploy/README.md).
APP_STACKS = {"dev": "loopboard", "prod": "loopboard-prod"}
#: How long one (alert, environment) pair is left alone after a session, so a
#: flapping alert does not start a session per flap.
COOLDOWN_SECONDS = int(os.environ.get("ALERT_AGENT_COOLDOWN_SECONDS", "3600"))


def log(message: str) -> None:
    print(f"{datetime.now().astimezone().strftime('%H:%M:%S')} {message}", flush=True)


# ---------------------------------------------------------------- AWS (ours) --


def aws(*args: str) -> str:
    """The AWS CLI with the operator's credentials. Used only by this script."""
    result = subprocess.run(["aws", *args, "--output", "text"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args[:2])}: {result.stderr.strip()}")
    return result.stdout.strip()


def stack_output(stack: str, key: str) -> str:
    return aws(
        "cloudformation", "describe-stacks", "--stack-name", stack,
        "--query", f"Stacks[0].Outputs[?OutputKey=='{key}'].OutputValue | [0]",
    )


def stack_instance(stack: str) -> str:
    return aws(
        "cloudformation", "describe-stack-resource", "--stack-name", stack,
        "--logical-resource-id", "Instance", "--query", "StackResourceDetail.PhysicalResourceId",
    )


#: Run on the app instance to collect evidence. Fixed and read-only: nothing
#: here writes, restarts or reads a secret (.env, which holds the database
#: password, is never read; deploy.env holds none).
INSTANCE_COMMANDS = [
    "echo '## image'; cat /etc/loopboard/image",
    "echo '## deploy.env'; cat /etc/loopboard/deploy.env",
    "echo '## containers'; cd /opt/loopboard/app/deploy && docker compose -f docker-compose.prod.yaml ps",
    # The container health check calls /health every 3 s; left in, it is
    # nearly every line of the tail and pushes out the ones that matter.
    (
        "echo '## app logs, last 30 min, health checks left out'; cd /opt/loopboard/app/deploy && "
        "docker compose -f docker-compose.prod.yaml logs --no-color --since 30m app "
        "| grep -v '\"GET /health ' | tail -n 400"
    ),
]


def instance_evidence(stack: str) -> str:
    instance = stack_instance(stack)
    command_id = aws(
        "ssm", "send-command", "--instance-ids", instance,
        "--document-name", "AWS-RunShellScript",
        "--comment", "alert-agent: read-only evidence",
        "--parameters", json.dumps({"commands": INSTANCE_COMMANDS}),
        "--query", "Command.CommandId",
    )
    for _ in range(30):
        time.sleep(3)
        try:
            status = aws(
                "ssm", "get-command-invocation", "--command-id", command_id,
                "--instance-id", instance, "--query", "Status",
            )
        except RuntimeError:
            continue
        if status not in {"Pending", "InProgress", "Delayed"}:
            break
    output = aws(
        "ssm", "get-command-invocation", "--command-id", command_id,
        "--instance-id", instance, "--query", "StandardOutputContent",
    )
    # SSE requests carry the participant token in the query string, and the
    # access log prints it.
    return f"instance {instance} ({stack})\n\n" + re.sub(r"token=[^&\s\"]+", "token=REDACTED", output)


# ------------------------------------------------------------------- Grafana --


class Grafana:
    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token

    def get(self, path: str, **params: str) -> dict:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        return self._request(urllib.request.Request(f"{self.url}{path}{query}"))

    def post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            f"{self.url}{path}", json.dumps(body).encode(), {"content-type": "application/json"}
        )
        return self._request(request)

    def _request(self, request: urllib.request.Request) -> dict:
        request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def firing(self) -> list[dict]:
        alerts = self.get("/api/prometheus/grafana/api/v1/alerts")["data"]["alerts"]
        # The list includes every rule's instances, healthy ones too.
        return [alert for alert in alerts if alert["state"].startswith("Alerting")]

    def prometheus(self, expr: str, minutes: int = 30) -> list[dict]:
        body = {
            "queries": [{"refId": "A", "datasource": {"uid": "prometheus"}, "expr": expr, "instant": True}],
            "from": f"now-{minutes}m",
            "to": "now",
        }
        frames = self.post("/api/ds/query", body)["results"]["A"].get("frames", [])
        return [
            {"labels": frame["schema"]["fields"][1].get("labels", {}), "value": frame["data"]["values"][1][-1]}
            for frame in frames
        ]

    def error_traces(self, environment: str) -> list[dict]:
        query = f'{{resource.deployment.environment.name="{environment}" && status=error}}'
        return self.get(
            "/api/datasources/proxy/uid/tempo/api/search", q=query, limit="10", spss="20"
        ).get("traces", [])


def metrics_evidence(grafana: Grafana, environment: str) -> str:
    env = f'deployment_environment_name="{environment}"'
    queries = {
        "5xx in the last 30 min, by route and status": (
            f'sum by (http_method, http_target, http_status_code) '
            f'(increase(http_server_duration_milliseconds_count{{{env}, http_status_code=~"5.."}}[30m]))'
        ),
        "all requests in the last 30 min, by route": (
            f"sum by (http_method, http_target) (increase(http_server_duration_milliseconds_count{{{env}}}[30m]))"
        ),
        "commit(s) serving requests (vcs_ref_head_revision)": (
            f"count by (vcs_ref_head_revision, service_version) (http_server_duration_milliseconds_count{{{env}}})"
        ),
        "elements created in the last 30 min, by type": (
            f"sum by (element_type) (increase(loopboard_canvas_elements_created_total{{{env}}}[30m]))"
        ),
    }
    sections = []
    for title, expr in queries.items():
        rows = grafana.prometheus(expr)
        lines = [f"  {row['labels']} = {row['value']:.1f}" for row in rows] or ["  (no data)"]
        sections.append(f"### {title}\n`{expr}`\n" + "\n".join(lines))
    return "\n\n".join(sections)


# ----------------------------------------------------------------- incidents --


SEVERITY_ORDER = {"critical": 0, "warning": 1}


def by_severity(alerts: list[dict]) -> list[dict]:
    return sorted(alerts, key=lambda alert: SEVERITY_ORDER.get(alert["labels"].get("severity"), 9))


def incident_id(environment: str, alerts: list[dict]) -> str:
    """Named after the most severe alert, which is usually the most specific."""
    slug = re.sub(r"[^a-z0-9]+", "-", alerts[0]["labels"]["alertname"].lower()).strip("-")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{environment}-{slug}"


def fingerprint(alert: dict) -> str:
    labels = alert["labels"]
    return f"{labels['alertname']}|{labels.get('deployment_environment_name')}"


def load_state() -> dict:
    try:
        return json.loads((STATE_DIR / "state.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "state.json").write_text(json.dumps(state, indent=2))


def gather_evidence(grafana: Grafana, environment: str, alerts: list[dict], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "alerts.json").write_text(json.dumps(alerts, indent=2))

    def collect(name: str, produce) -> None:
        try:
            (directory / name).write_text(produce())
        except Exception as error:  # noqa: BLE001 - best effort; record what is missing
            (directory / name).write_text(f"(could not collect: {error})\n")
            log(f"  evidence {name}: {error}")

    collect("metrics.md", lambda: metrics_evidence(grafana, environment))
    collect("error-traces.json", lambda: json.dumps(grafana.error_traces(environment), indent=2))
    stack = APP_STACKS.get(environment)
    if stack:
        collect("instance.txt", lambda: instance_evidence(stack))
    else:
        (directory / "instance.txt").write_text(f"(no app stack known for environment {environment!r})\n")


def make_worktree(incident: str) -> Path:
    """A clean checkout of origin/main for this incident, on its own branch."""
    worktree = STATE_DIR / "worktrees" / incident
    subprocess.run(["git", "-C", str(REPO_ROOT), "fetch", "-q", "origin", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "add", "-q", "-b", f"alert-agent/{incident}",
         str(worktree), "origin/main"],
        check=True,
    )
    return worktree


def render_prompt(
    environment: str, alerts: list[dict], incident: str, incident_dir: Path, grafana_url: str
) -> str:
    template = (HERE / "prompt.md").read_text()
    listing = "\n".join(
        f"- **{alert['labels']['alertname']}** ({alert['labels'].get('severity', '?')}), "
        f"firing since {alert.get('activeAt', '?')}: {alert['annotations'].get('summary', '')}"
        for alert in alerts
    )
    values = {
        "ALERTS": listing,
        "ENVIRONMENT": environment,
        "INCIDENT": incident,
        "QUERY": f"python3 {HERE / 'grafana_query.py'}",
        "INCIDENT_DIR": str(incident_dir),
        "EVIDENCE_DIR": str(incident_dir / "evidence"),
        "REPORT": str(incident_dir / "report.md"),
        "APP_PATH": str(APP_PATH),
        "BRANCH": f"alert-agent/{incident}",
        "GRAFANA_URL": grafana_url,
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


#: Tools the session may use without asking; in print mode anything else is
#: refused. Bash rules are prefix matches — a guard rail, not a sandbox; the
#: hard limits are the missing AWS credentials and the Viewer-only token.
#: Grafana is reached through grafana_query.py, which only reads, rather than
#: curl, whose permission rule cannot tell a read from a write.
ALLOWED_TOOLS = [
    "Read", "Grep", "Glob", "Edit", "Write", "TodoWrite",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git blame:*)", "Bash(git add:*)", "Bash(git commit:*)", "Bash(git grep:*)",
    "Bash(git push -u origin alert-agent/:*)",
    "Bash(gh pr create:*)",
    f"Bash(python3 {HERE / 'grafana_query.py'}:*)",
    "Bash(cd:*)",
    "Bash(uv sync:*)", "Bash(uv run pytest:*)", "Bash(uv run python -m pytest:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(grep:*)", "Bash(jq:*)",
]
DISALLOWED_TOOLS = [
    "Bash(aws:*)", "Bash(ssh:*)", "Bash(docker:*)", "Bash(gh workflow:*)", "Bash(gh api:*)",
    "Bash(gh pr merge:*)", "Bash(git push origin main:*)", "Bash(git push --force:*)",
    "Bash(git push -f:*)", "WebFetch", "WebSearch",
]


def claude_environment(grafana: Grafana) -> dict[str, str]:
    """The session's environment: no AWS credentials of any kind."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
    env.update(
        AWS_CONFIG_FILE="/dev/null",
        AWS_SHARED_CREDENTIALS_FILE="/dev/null",
        AWS_EC2_METADATA_DISABLED="true",
        GRAFANA_URL=grafana.url,
        GRAFANA_TOKEN=grafana.token,
    )
    return env


def run_claude(prompt: str, worktree: Path, incident_dir: Path, grafana: Grafana, args) -> int:
    command = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *DISALLOWED_TOOLS,
        "--add-dir", str(incident_dir),
        "--max-budget-usd", str(args.budget),
        # None of the operator's MCP servers: one of them could be an AWS
        # server, a way around the stripped credentials.
        "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}',
    ]
    if args.model:
        command += ["--model", args.model]
    log(f"  claude: session in {worktree} (budget ${args.budget})")
    with (incident_dir / "claude.json").open("w") as transcript, \
            (incident_dir / "claude.stderr").open("w") as errors:
        result = subprocess.run(
            command, cwd=worktree, env=claude_environment(grafana), stdin=subprocess.DEVNULL,
            stdout=transcript, stderr=errors, timeout=args.timeout, check=False,
        )
    return result.returncode


def handle(environment: str, alerts: list[dict], grafana: Grafana, args) -> None:
    """One incident, and one session, for everything newly firing in one
    environment: a single fault usually trips several rules at once."""
    alerts = by_severity(alerts)
    incident = incident_id(environment, alerts)
    incident_dir = STATE_DIR / "incidents" / incident
    for alert in alerts:
        log(f"FIRING {alert['labels']['alertname']} on {environment}"
            f" — {alert['annotations'].get('summary', '')}")
    log(f"  incident {incident}: gathering evidence")
    gather_evidence(grafana, environment, alerts, incident_dir / "evidence")
    prompt = render_prompt(environment, alerts, incident, incident_dir, grafana.url)
    (incident_dir / "prompt.md").write_text(prompt)
    if args.dry_run:
        log(f"  dry run: evidence and prompt in {incident_dir}")
        return
    worktree = make_worktree(incident)
    try:
        code = run_claude(prompt, worktree, incident_dir, grafana, args)
    except subprocess.TimeoutExpired:
        code = -1
        log(f"  claude: timed out after {args.timeout}s")
    report = incident_dir / "report.md"
    log(f"  claude: exit {code}; report {'at ' + str(report) if report.exists() else 'NOT written'}")
    if report.exists():
        print(report.read_text(), flush=True)
    # Clean up what the session left unused. A checkout with uncommitted work
    # stays for a human to look at; a branch with commits stays, since a PR
    # may point at it. A branch with nothing on it goes with its checkout.
    def git(*command: str) -> str:
        return subprocess.run(["git", "-C", str(REPO_ROOT), *command],
                              capture_output=True, text=True, check=False).stdout.strip()

    dirty = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain"],
                           capture_output=True, text=True, check=False).stdout.strip()
    if not dirty:
        git("worktree", "remove", str(worktree))
        branch = f"alert-agent/{incident}"
        if not git("rev-list", f"origin/main..{branch}"):
            git("branch", "-D", branch)


def poll(grafana: Grafana, args) -> None:
    state = load_state()
    now = time.time()
    fresh: dict[str, list[dict]] = {}
    for alert in grafana.firing():
        environment = alert["labels"].get("deployment_environment_name") or "unknown"
        if args.env and environment not in args.env:
            continue
        last = state.get(fingerprint(alert), {})
        if last.get("activeAt") == alert.get("activeAt"):
            continue  # this firing already had its session
        if now - last.get("handledAt", 0) < COOLDOWN_SECONDS:
            continue
        fresh.setdefault(environment, []).append(alert)
    for environment, alerts in fresh.items():
        handle(environment, alerts, grafana, args)
        if not args.dry_run:  # a dry run must not use up the alerts' session
            for alert in alerts:
                state[fingerprint(alert)] = {"activeAt": alert.get("activeAt"), "handledAt": time.time()}
            save_state(state)


def connect() -> Grafana:
    url = os.environ.get("GRAFANA_URL") or stack_output(OBS_STACK, "GrafanaUrl")
    token = os.environ.get("GRAFANA_TOKEN") or aws(
        "ssm", "get-parameter", "--with-decryption", "--name", TOKEN_PARAMETER,
        "--query", "Parameter.Value",
    )
    return Grafana(url, token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--dry-run", action="store_true", help="gather evidence and write the prompt; no Claude")
    parser.add_argument("--interval", type=int, default=30, help="seconds between polls (default 30)")
    parser.add_argument("--env", action="append", help="only these environments (repeatable)")
    parser.add_argument("--budget", type=float, default=5.0, help="max USD per session (default 5)")
    parser.add_argument("--timeout", type=int, default=1800, help="max seconds per session (default 1800)")
    parser.add_argument("--model", help="Claude model for the session (default: your configured one)")
    args = parser.parse_args()

    if not args.dry_run and not shutil.which("claude"):
        sys.exit("claude (Claude Code) is not on PATH")
    grafana = connect()
    log(f"watching {grafana.url} every {args.interval}s; state in {STATE_DIR}")
    while True:
        try:
            poll(grafana, args)
        except (urllib.error.URLError, RuntimeError, KeyError) as error:
            log(f"poll failed: {error}")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
