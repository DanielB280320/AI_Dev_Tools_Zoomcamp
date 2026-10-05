# Alert agent

A watcher that polls Loopboard's Grafana alerts. When one fires, it starts a
headless Claude Code session that works out what's wrong and proposes the fix.

```
Grafana alerts ──poll 30 s──▶ watch.py ──firing──▶ gather evidence ──▶ claude -p (headless)
                                                    · metrics, error traces       │
                                                    · instance: image, settings,  ├─▶ report.md
                                                      containers, app logs        └─▶ PR on alert-agent/<id>
                                                      (read-only, via SSM)            (code causes only)
```

```bash
make alert-agent             # watch until Ctrl-C
make alert-agent-dry-run     # one poll; gather evidence and write the prompt, no Claude
python3 ops/alert-agent/watch.py --once --env prod --budget 3   # one poll, prod only
```

It runs on this machine, with your Claude Code login, AWS and `gh` credentials.
It needs Python 3.11+ and nothing else, and nothing runs in the cloud.

## What happens when an alert fires

1. **Grouping.** Every alert that's newly firing in one environment becomes
   **one incident**. A single fault usually trips several rules (canvas errors,
   then overall API errors), and they get one session between them.
2. **Evidence.** The watcher collects it itself, with fixed read-only commands,
   into `~/.local/state/loopboard-alert-agent/incidents/<id>/evidence/`:
   - `alerts.json`: the alerts.
   - `metrics.md`: 5xx by route, request mix, the serving commit, elements created.
   - `error-traces.json`: recent error traces from Tempo.
   - `instance.txt`: from that environment's app instance over SSM: the running
     image, `deploy.env`, container status and 30 minutes of app logs, with
     tokens redacted.
3. **Session.** `claude -p` runs in a fresh git worktree off `origin/main`, on
   branch `alert-agent/<id>`, with `prompt.md` filled in. It writes
   `report.md` (verdict, root cause with evidence, impact, fix, how to verify,
   follow-ups):
   - **Code cause:** it fixes it on the branch, runs the backend tests, pushes
     and opens a PR.
   - **Config or ops cause:** it writes the exact commands for a human to run,
     and changes no code.
4. **Done.** The report is printed, and the full transcript is in
   `claude.json`. Each alert gets one session per firing, and the same alert
   on the same environment then waits an hour before another
   (`ALERT_AGENT_COOLDOWN_SECONDS`).

## Boundaries

The agent diagnoses and proposes; a human applies anything that touches an
environment. That's enforced by what the session is given, not by asking it
nicely:

| Limit | How |
| --- | --- |
| No AWS access | The session's environment has no AWS credentials (`AWS_*` removed, config files pointed at `/dev/null`). Every `aws` command is denied, and no MCP servers are loaded. |
| Read-only Grafana | A **Viewer** service-account token. Queries go through `grafana_query.py`, which only reads. |
| No changes to `main` or prod | Pushes are allowed only to `alert-agent/…`; pushing `main`, force-pushing, merging and running workflows are denied. |
| Bounded | `--max-budget-usd` (default $5) and a 30-minute timeout per session. |
| No escape hatches | Only listed commands run. `bash script.sh`, `git -C …`, ad-hoc `curl`, `ssh` and `docker` are refused (seen in testing). |

The Bash rules are prefix matches, so they're a guard rail rather than a
sandbox. The hard limits are the missing AWS credentials and the Viewer token.
Your `gh` login can still push to `main`, so turn on branch protection for
`main` on GitHub if you want that enforced too.

## Setup

The Grafana token is a Viewer service account, `alert-agent`, stored in SSM:

```bash
aws ssm get-parameter --with-decryption --name /loopboard-observability/alert-agent-grafana-token
```

`GRAFANA_URL` and `GRAFANA_TOKEN` in the environment override the stack output
and the SSM parameter, for example to point at a local Grafana. State lives in
`~/.local/state/loopboard-alert-agent` (`ALERT_AGENT_HOME`).

## Cost

Each session is billed to your Claude Code account. In testing, a
config-caused incident took about 2 minutes and $0.65–0.70. A code fix with a
test run costs more. `--budget` caps each session.
