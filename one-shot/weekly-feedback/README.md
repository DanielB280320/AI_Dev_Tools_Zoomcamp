# wfb — weekly feedback for projects

A small command-line tool for collecting one short feedback entry per project
per week, then turning those into a digest you can paste into a status email,
a wiki page, or a Slack post.

No dependencies — Python 3.11+ and the standard library only. Data lives in a
single JSON file you can read, diff, and commit.

```
$ wfb report --week 2026-W36

# Weekly feedback - 2026-W36

_Aug 31 - Sep 06, 2026_

- **Coverage:** 2/3 projects reported (67%)
- **Status:** 🟢 1 · 🟡 0 · 🔴 1
- **Average rating:** 3.5 / 5

## 🔴 Borealis API (`borealis`)
status **red** · rating **2/5** · by _sam_

**Blockers**
- Flaky integration suite blocks every deploy
...
```

## Install

Nothing to install. Run it from the checkout:

```bash
./wfb.py --help            # or: python3 wfb.py --help
python3 -m weekly_feedback --help
```

An alias makes it feel installed:

```bash
alias wfb="python3 /path/to/weekly-feedback/wfb.py"
```

## Quick start

```bash
wfb project add apollo --name "Apollo Rewrite" --owner dana
wfb project add borealis --name "Borealis API" --owner sam

wfb submit apollo --status green --rating 5 --author dana \
  --highlight "Beta shipped to 200 users" \
  --lowlight  "Docs still lag the API" \
  --next      "Open it to everyone" \
  --note      "Best week of the quarter."

wfb report                  # this week's digest, as Markdown
wfb check                   # exit 1 if anyone hasn't reported yet
wfb trend --weeks 8         # status history at a glance
```

`./demo.sh` runs that whole flow against a throwaway data file so you can see
every command's output without touching your own data.

## Concepts

- **Project** — something you want feedback on every week. Identified by a
  short slug (`apollo`), with an optional display name and owner. Archive a
  project to keep its history but stop expecting new entries.
- **Entry** — one project's feedback for one ISO week. At most one entry per
  project per week; a second `submit` must say `--replace` or `--append`.
- **Status** — `green` (on track), `amber` (at risk), `red` (off track).
  Aliases are accepted: `ok`, `yellow`, `at-risk`, `blocked`, `g`/`a`/`r`.
- **Week** — always an ISO week key like `2026-W36`. Anywhere a `--week` is
  taken you can write `2026-W36`, a `YYYY-MM-DD` date inside the week,
  `current` / `last` / `next`, or an offset like `-2`.

## Commands

| Command | What it does |
| --- | --- |
| `project add <slug>` | Start tracking a project (`--name`, `--owner`) |
| `project list` | Projects with this week's reporting status (`--all` includes archived) |
| `project archive/restore <slug>` | Stop / resume expecting weekly feedback |
| `project rm <slug>` | Delete a project (`--with-entries` to drop its history too) |
| `submit <slug>` | Record feedback for a week |
| `show <slug>` | Show one project's entry for a week (`--json` for raw) |
| `list` | List entries, filtered by `--project`, `--week`, `--status` |
| `rm <slug>` | Delete one entry |
| `report` | Weekly digest — `--format markdown\|text\|json`, `--out FILE` |
| `trend [slug]` | Status strip and rating sparkline over recent weeks |
| `check` | Exit non-zero if an active project hasn't reported |
| `export` | All entries as `--format csv\|json` |

Run `wfb <command> --help` for the full flag list.

### submit

```bash
wfb submit apollo \
  --week 2026-W36 \          # default: the current week
  --status amber \           # default: green (or the existing status on --append)
  --rating 3 \               # optional 1-5
  --author dana \
  --highlight "..." \        # each list flag is repeatable
  --lowlight  "..." \
  --blocker   "..." \
  --next      "..." \
  --note "free-form commentary"
```

An entry needs at least one highlight, lowlight, blocker, next step, or note —
a status on its own isn't feedback.

`-i` / `--interactive` prompts for each field instead, which is easier than
quoting a dozen flags:

```bash
wfb submit apollo -i
```

Submitting twice for the same week is refused by default so you don't quietly
lose someone's writeup. Choose explicitly:

- `--replace` overwrites the week's entry.
- `--append` merges into it: list items are added, notes are concatenated, and
  the status and rating stay as they were unless you pass new ones.

### report

`--format markdown` (default) is meant for pasting into a doc or a chat.
`--format text` is the compact terminal view. `--format json` is the machine
view — coverage counts, per-status totals, average rating, entries, and who
hasn't reported:

```bash
wfb report --week last --format json | jq '.coverage'
```

Worst status leads the digest, so whatever needs attention is at the top, and
projects that didn't report are listed at the end rather than silently omitted.

### check

`check` is the piece meant for automation: it exits `1` when an active project
has no entry for the week, so a Friday cron job can nag.

```bash
wfb check --week current || wfb report --format markdown --out digest.md
```

## Data file

Default location `~/.weekly-feedback/data.json`, overridden by the `WFB_DATA`
environment variable or `--data PATH` on any command:

```bash
WFB_DATA=./team-feedback.json wfb report
wfb --data ./team-feedback.json submit apollo --note "..."
```

Keeping the file in a repo gives you review and history for free. Writes are
atomic (temp file plus rename), so an interrupted run can't leave a truncated
file behind. The shape is stable and easy to hand-edit:

```json
{
  "version": 1,
  "projects": [
    {"slug": "apollo", "name": "Apollo Rewrite", "owner": "dana",
     "archived": false, "created_at": "2026-09-02T18:55:51+00:00"}
  ],
  "entries": [
    {"project": "apollo", "week": "2026-W36", "status": "green",
     "author": "dana", "rating": 5, "highlights": ["Beta shipped"],
     "lowlights": [], "blockers": [], "next_steps": [], "notes": "",
     "created_at": "...", "updated_at": "..."}
  ]
}
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

37 tests covering week parsing (including the year boundary and 53-week
years), validation, storage round-trips, report assembly, and every CLI
command.

## Layout

```
wfb.py                      entry point
demo.sh                     end-to-end walkthrough on throwaway data
weekly_feedback/
  weeks.py                  ISO week parsing and arithmetic
  models.py                 Project and Entry, plus input validation
  storage.py                atomic JSON persistence
  report.py                 digest assembly and the markdown/text/trend renderers
  cli.py                    argument parsing and commands
tests/
  test_weekly_feedback.py
```
