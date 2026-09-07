# weekly-feedback

A small CLI that produces **weekly feedback for project repositories**: what changed in
the last seven days, how healthy the project looks, and what to do next.

It reads git history and the tracked file list — no services, no API keys, no
third-party packages. Python 3.11+ and `git` are the only requirements.

## Why

Zoomcamp-style projects live or die on weekly momentum. This tool answers the three
questions a reviewer (or your future self) asks every Monday:

1. Did work actually land this week, and was it spread out or crammed into one night?
2. Is the project reviewable — README, tests, dependencies, CI, no secrets in git?
3. What are the highest-value things to fix next?

## Install

Nothing to install — run it from the source tree:

```bash
cd one-shot/weekly-feedback
python3 -m weekly_feedback --help
```

To get a `weekly-feedback` command on your PATH, either symlink the bundled wrapper:

```bash
ln -s "$PWD/bin/weekly-feedback" ~/.local/bin/weekly-feedback
```

...or install the package if you have pip available:

```bash
pip install -e .
```

## Usage

```bash
weekly-feedback                            # the repository in the current directory
weekly-feedback ~/projects/capstone        # one project
weekly-feedback ~/proj/a ~/proj/b          # several projects, with a summary table
weekly-feedback --scan ~/projects          # every git repository under a directory
weekly-feedback --days 14                  # a fortnight instead of a week
weekly-feedback --end 2026-08-31           # a window that ended in the past
weekly-feedback --format text              # coloured terminal output
weekly-feedback --format json              # machine-readable
weekly-feedback --out reports/week-35.md   # write to a file
weekly-feedback init                       # create a weekly-feedback.toml
```

### Options

| Option | Meaning |
| --- | --- |
| `paths...` | Repositories to analyse. Any path inside a work tree resolves to its root. |
| `--scan DIR` | Treat every git repository under `DIR` as a project (repeatable). |
| `--days N` | Window length in days (default `7`). |
| `--end DATE` | End of the window, `YYYY-MM-DD` or a full timestamp (default: now). A bare date means end of that day. |
| `--format` | `markdown` (default), `text`, or `json`. |
| `--out FILE` | Write the report to `FILE` instead of stdout. |
| `--fail-under N` | Exit `1` if any project scores below `N` — useful in CI or a cron job. |
| `--config FILE` / `--no-config` | Use a specific config file, or ignore config discovery. |
| `--color` / `--no-color` | Force or suppress ANSI colour in `text` output. |

Exit codes: `0` success, `1` a project fell below `--fail-under`, `2` a usage or
configuration error.

## Configuration

`weekly-feedback` looks for `weekly-feedback.toml`, `.weekly-feedback.toml`, or
`projects.toml` in the current directory and its parents. Command line flags always
win over the file.

```toml
[defaults]
days = 7
format = "markdown"
fail_under = 60

[[projects]]
name = "capstone"
path = "~/projects/capstone"
```

`[defaults] scan = ["~/projects"]` picks up every repository under a directory instead
of listing them one by one. A `.json` file with the same shape works too.

## What it measures

**Activity (40% of the score)** — commits, active days, insertions/deletions, files
touched, contributors, merge share, median commit size, conventional-commit rate, and
the comparison against the immediately preceding window of the same length.

**Project health (60% of the score)** — a weighted rubric over the tracked file list:

| Check | Points |
| --- | --- |
| README at the project root (partial credit if under 400 bytes) | 3 |
| Automated tests (partial credit for a single test file) | 3 |
| No credential-shaped files committed (`.env`, `*.pem`, keys, …) | 3 |
| Declared dependencies (`requirements.txt`, `pyproject.toml`, `package.json`, …) | 2 |
| Continuous integration (GitHub Actions, GitLab CI, CircleCI, …) | 2 |
| `.gitignore` present | 1 |
| Documentation beyond the README | 1 |
| Reproducible runtime (`Dockerfile` / compose) | 1 |
| License file | 1 |
| No tracked file over 5 MB | 1 |

Those feed three narrative sections per project — **what went well**, **needs
attention**, **suggested next steps** — plus a letter grade (A ≥ 90, B ≥ 80, C ≥ 70,
D ≥ 60, otherwise F).

## Example output

```markdown
## capstone — grade B (82/100)

`/home/dani/projects/capstone` on branch `main`

- **Activity:** 12 commits, up 4 vs the previous window (8); 5 active days; +820/-310 across 23 files
- **Contributors:** Dani
- **Scores:** activity 100/100, health 71/100 (12.5 of 18 rubric points)

### What went well
- Steady cadence: work landed on 5 separate days rather than one push.
- Commit messages follow a consistent conventional format.

### Needs attention
- Continuous integration: no CI configuration.

### Suggested next steps
1. Add a GitHub Actions workflow that installs deps and runs the tests on every push.
```

## Automating it

A weekly cron entry that writes a dated report:

```cron
0 9 * * MON  cd ~/projects && weekly-feedback --scan . --out ~/reports/$(date +\%Y-W\%V).md
```

Or gate a repository in CI with `weekly-feedback --fail-under 70`.

## Development

```bash
python -m unittest discover -s tests -t .
```

112 tests, standard library only. `tests/helpers.py` builds throwaway git repositories
with controlled commit dates, so the git-facing code is tested against real
repositories rather than mocks.

Layout:

| Module | Responsibility |
| --- | --- |
| `weekly_feedback/gitstats.py` | Shells out to git; parses `git log --numstat` into commits and window aggregates. |
| `weekly_feedback/health.py` | The rubric — scores a project from its tracked file list. |
| `weekly_feedback/feedback.py` | Turns activity + health into highlights, concerns, next steps, and a grade. |
| `weekly_feedback/report.py` | Markdown, terminal, and JSON renderers. |
| `weekly_feedback/config.py` | TOML/JSON config discovery and parsing. |
| `weekly_feedback/cli.py` | Argument parsing, window maths, orchestration. |
