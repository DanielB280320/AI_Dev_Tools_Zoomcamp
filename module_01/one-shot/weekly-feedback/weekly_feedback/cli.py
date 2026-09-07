"""Command line entry point for weekly project feedback."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from weekly_feedback import __version__, config as config_mod
from weekly_feedback import feedback as feedback_mod
from weekly_feedback import gitstats, health, report

EPILOG = """\
examples:
  weekly-feedback                          report on the repository in the current directory
  weekly-feedback ~/projects/capstone      report on one project
  weekly-feedback --scan ~/projects        report on every repository under a directory
  weekly-feedback --days 14 --format text  a fortnight, printed for the terminal
  weekly-feedback --out feedback.md        write the Markdown report to a file
  weekly-feedback init                     create a weekly-feedback.toml
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weekly-feedback",
        description="Generate weekly feedback for one or more project repositories.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"weekly-feedback {__version__}")

    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="write a sample weekly-feedback.toml")
    init.add_argument(
        "--out",
        type=Path,
        default=Path("weekly-feedback.toml"),
        help="where to write the sample config (default: ./weekly-feedback.toml)",
    )
    init.add_argument("--force", action="store_true", help="overwrite an existing file")

    _add_report_arguments(sub.add_parser("report", help="generate the feedback report (default)"))
    return parser


def _add_report_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="project repositories to analyse (default: the current directory or the config file)",
    )
    parser.add_argument("--config", type=Path, help="path to a weekly-feedback.toml / .json")
    parser.add_argument("--no-config", action="store_true", help="ignore any discovered config file")
    parser.add_argument("--scan", type=Path, action="append", default=[], metavar="DIR",
                        help="treat every git repository under DIR as a project (repeatable)")
    parser.add_argument("--days", type=int, help="length of the window in days (default: 7)")
    parser.add_argument("--end", metavar="YYYY-MM-DD", help="end of the window (default: now)")
    parser.add_argument("--format", choices=["markdown", "md", "text", "json"],
                        help="output format (default: markdown)")
    parser.add_argument("--out", type=Path, metavar="FILE", help="write the report to FILE instead of stdout")
    parser.add_argument("--fail-under", type=int, metavar="SCORE",
                        help="exit with status 1 if any project scores below SCORE")
    parser.add_argument("--color", action="store_true", help="force ANSI colour in text output")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")


def parse_end(value: str | None) -> datetime:
    now = datetime.now().astimezone()
    if not value:
        return now
    text = value.strip()
    if text.lower() in {"now", "today"}:
        return now
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit(f"error: could not parse --end {value!r}; use YYYY-MM-DD") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    if parsed.hour == parsed.minute == parsed.second == 0:
        parsed = parsed + timedelta(days=1) - timedelta(seconds=1)
    return parsed


def make_windows(end: datetime, days: int) -> tuple[gitstats.Window, gitstats.Window]:
    span = timedelta(days=max(1, days))
    current = gitstats.Window(start=end - span, end=end)
    previous = gitstats.Window(start=current.start - span, end=current.start)
    return current, previous


def resolve_projects(args: argparse.Namespace, cfg: config_mod.Config) -> list[config_mod.ProjectSpec]:
    specs: list[config_mod.ProjectSpec] = []
    seen: set[Path] = set()

    def add(path: Path, name: str | None = None) -> None:
        try:
            root = gitstats.repo_root(path)
        except gitstats.NotAGitRepository as exc:
            print(f"warning: skipping {path} — {exc}", file=sys.stderr)
            return
        if root in seen:
            return
        seen.add(root)
        specs.append(config_mod.ProjectSpec(name=name or root.name, path=root))

    for path in args.paths:
        add(path)
    for spec in cfg.projects:
        add(spec.path, spec.name)
    for directory in [*args.scan, *cfg.scan]:
        for found in gitstats.discover_repos(directory):
            add(found)

    if not specs and not args.paths and not cfg.projects and not args.scan and not cfg.scan:
        add(Path.cwd())
    return specs


def analyse(spec: config_mod.ProjectSpec, current: gitstats.Window, previous: gitstats.Window) -> feedback_mod.ProjectFeedback:
    snap = gitstats.snapshot(spec.path)
    activity = gitstats.collect(spec.path, current)
    prior = gitstats.collect(spec.path, previous)
    rubric = health.evaluate(snap.tracked_files, root=spec.path)
    return feedback_mod.build(
        name=spec.name,
        path=spec.path,
        window=current,
        snapshot=snap,
        current=activity,
        previous=prior,
        health=rubric,
    )


def cmd_init(args: argparse.Namespace) -> int:
    target: Path = args.out
    if target.exists() and not args.force:
        print(f"error: {target} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_mod.SAMPLE_CONFIG, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    cfg = config_mod.Config()
    if not args.no_config:
        config_path = args.config or config_mod.find_config(Path.cwd())
        if config_path:
            try:
                cfg = config_mod.load(config_path)
            except config_mod.ConfigError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2

    days = args.days if args.days is not None else cfg.days
    if days < 1:
        print("error: --days must be at least 1", file=sys.stderr)
        return 2
    fmt = args.format or cfg.format
    fail_under = args.fail_under if args.fail_under is not None else cfg.fail_under
    destination = args.out or cfg.output

    current, previous = make_windows(parse_end(args.end), days)
    specs = resolve_projects(args, cfg)
    if not specs:
        print("error: no git repositories to analyse", file=sys.stderr)
        return 2

    reports = []
    for spec in specs:
        try:
            reports.append(analyse(spec, current, previous))
        except gitstats.GitError as exc:
            print(f"warning: skipping {spec.name} — {exc}", file=sys.stderr)
    if not reports:
        print("error: every project failed to analyse", file=sys.stderr)
        return 2

    use_color = args.color or (not args.no_color and destination is None and sys.stdout.isatty())
    text = report.render(reports, fmt=fmt, color=use_color)

    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        print(f"wrote {destination} ({len(reports)} project(s))")
    else:
        sys.stdout.write(text)

    if fail_under:
        failing = [r for r in reports if r.score < fail_under]
        if failing:
            names = ", ".join(f"{r.name} ({r.score})" for r in failing)
            print(f"below --fail-under {fail_under}: {names}", file=sys.stderr)
            return 1
    return 0


COMMANDS = ("report", "init")
PASSTHROUGH = ("-h", "--help", "--version")


def normalize(argv: list[str]) -> list[str]:
    """Allow the report subcommand to be omitted: `weekly-feedback ~/repo`."""
    if argv and (argv[0] in COMMANDS or argv[0] in PASSTHROUGH):
        return list(argv)
    return ["report", *argv]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalize(list(sys.argv[1:] if argv is None else argv)))
    if args.command == "init":
        return cmd_init(args)
    return cmd_report(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
