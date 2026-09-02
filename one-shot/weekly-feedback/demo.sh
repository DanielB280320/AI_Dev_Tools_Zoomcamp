#!/usr/bin/env bash
# End-to-end walkthrough against a throwaway data file.
# Usage: ./demo.sh
set -euo pipefail

cd "$(dirname "$0")"
export WFB_DATA="${TMPDIR:-/tmp}/wfb-demo-$$.json"
trap 'rm -f "$WFB_DATA"' EXIT

wfb() { python3 ./wfb.py "$@"; }
# `check` exits non-zero by design when a project has not reported, so don't
# let that stop the walkthrough.
step() { printf '\n\033[1m$ wfb %s\033[0m\n' "$*"; wfb "$@" || printf '(exit %s)\n' "$?"; }

step project add apollo --name "Apollo Rewrite" --owner dana
step project add borealis --name "Borealis API" --owner sam
step project add zephyr --name "Zephyr Mobile" --owner ravi

step submit apollo --week 2026-W35 --status amber --rating 3 --author dana \
  --highlight "Migrated auth to the new service" \
  --blocker "Waiting on the infra ticket" \
  --next "Cut the beta build"

step submit apollo --week 2026-W36 --status green --rating 5 --author dana \
  --highlight "Beta shipped to 200 users" \
  --highlight "Latency down 40%" \
  --lowlight "Docs still lag the API" \
  --next "Open it to everyone" \
  --note "Best week of the quarter."

step submit borealis --week 2026-W36 --status red --rating 2 --author sam \
  --lowlight "Two rollbacks" \
  --blocker "Flaky integration suite blocks every deploy" \
  --next "Quarantine the flaky tests"

step submit borealis --week 2026-W36 --append --author sam \
  --blocker "Still short one reviewer"

step project list
step list --week 2026-W36
step check --week 2026-W36
step report --week 2026-W36 --format text
step report --week 2026-W36
step trend --week 2026-W36 --weeks 4
step export --format csv

printf '\n\033[1mDone.\033[0m Demo data file removed.\n'
