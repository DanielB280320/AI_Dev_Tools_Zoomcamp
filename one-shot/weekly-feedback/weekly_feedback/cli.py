"""Command-line interface for the weekly project feedback tool."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys

from . import report as reporting
from . import weeks as wk
from .models import (
    STATUS_ICONS,
    STATUSES,
    Entry,
    Project,
    ValidationError,
    normalize_status,
)
from .storage import Store, StorageError, default_path

PROG = "wfb"
__version__ = "1.0.0"


# --------------------------------------------------------------- parser ---
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Collect and report weekly feedback for the projects you track.",
        epilog=(
            "Weeks accept 2026-W36, a YYYY-MM-DD date, current/last/next, "
            "or an offset like -2."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument(
        "--data",
        metavar="PATH",
        help=f"data file to use (default: $WFB_DATA or {default_path()})",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # -- project -----------------------------------------------------------
    project = subparsers.add_parser("project", help="manage the tracked projects")
    project_subs = project.add_subparsers(dest="project_command", metavar="<action>")

    add = project_subs.add_parser("add", help="start tracking a project")
    add.add_argument("slug", help="short id, e.g. apollo")
    add.add_argument("--name", help="display name (defaults to the id)")
    add.add_argument("--owner", default="", help="who is accountable for it")
    add.set_defaults(func=cmd_project_add)

    listing = project_subs.add_parser("list", help="list tracked projects")
    listing.add_argument(
        "--all", action="store_true", help="include archived projects"
    )
    listing.set_defaults(func=cmd_project_list)

    archive = project_subs.add_parser(
        "archive", help="stop expecting weekly feedback for a project"
    )
    archive.add_argument("slug")
    archive.set_defaults(func=cmd_project_archive)

    restore = project_subs.add_parser("restore", help="un-archive a project")
    restore.add_argument("slug")
    restore.set_defaults(func=cmd_project_restore)

    remove = project_subs.add_parser("rm", help="delete a project")
    remove.add_argument("slug")
    remove.add_argument(
        "--with-entries",
        action="store_true",
        help="also delete that project's feedback history",
    )
    remove.set_defaults(func=cmd_project_rm)
    project.set_defaults(func=lambda args, store: _needs_subcommand(project))

    # -- submit ------------------------------------------------------------
    submit = subparsers.add_parser("submit", help="record feedback for one week")
    submit.add_argument("slug", help="project id")
    submit.add_argument("--week", help="week to file under (default: current week)")
    submit.add_argument(
        "--status",
        help=(
            f"one of {', '.join(STATUSES)} (aliases: ok/at-risk/blocked); "
            "defaults to green, or to the existing status when appending"
        ),
    )
    submit.add_argument("--author", default="", help="who is writing this")
    submit.add_argument("--rating", help="overall week rating, 1-5")
    submit.add_argument(
        "--highlight", action="append", default=[], help="what went well (repeatable)"
    )
    submit.add_argument(
        "--lowlight", action="append", default=[], help="what went badly (repeatable)"
    )
    submit.add_argument(
        "--blocker", action="append", default=[], help="what is in the way (repeatable)"
    )
    submit.add_argument(
        "--next", action="append", default=[], dest="next_steps",
        help="planned for next week (repeatable)",
    )
    submit.add_argument("--note", default="", help="free-form commentary")
    submit.add_argument(
        "-i", "--interactive", action="store_true", help="prompt for each field"
    )
    mode = submit.add_mutually_exclusive_group()
    mode.add_argument(
        "--replace", action="store_true", help="overwrite existing feedback for the week"
    )
    mode.add_argument(
        "--append", action="store_true", help="add to existing feedback for the week"
    )
    submit.set_defaults(func=cmd_submit)

    # -- show / list -------------------------------------------------------
    show = subparsers.add_parser("show", help="show one project's feedback for a week")
    show.add_argument("slug")
    show.add_argument("--week")
    show.add_argument("--json", action="store_true", help="print raw JSON")
    show.set_defaults(func=cmd_show)

    entries = subparsers.add_parser("list", help="list feedback entries")
    entries.add_argument("--project", help="filter by project id")
    entries.add_argument("--week", help="filter by week")
    entries.add_argument("--status", help=f"filter by status ({', '.join(STATUSES)})")
    entries.set_defaults(func=cmd_list)

    delete = subparsers.add_parser("rm", help="delete one feedback entry")
    delete.add_argument("slug")
    delete.add_argument("--week")
    delete.set_defaults(func=cmd_rm)

    # -- report / trend / check -------------------------------------------
    digest = subparsers.add_parser("report", help="weekly digest across projects")
    digest.add_argument("--week")
    digest.add_argument("--project", help="restrict the digest to one project")
    digest.add_argument(
        "--format", choices=("markdown", "text", "json"), default="markdown"
    )
    digest.add_argument("--out", metavar="FILE", help="write to a file instead of stdout")
    digest.set_defaults(func=cmd_report)

    trend = subparsers.add_parser("trend", help="status history over recent weeks")
    trend.add_argument("slug", nargs="?", help="one project (default: all active)")
    trend.add_argument("--week", help="last week to include (default: current)")
    trend.add_argument("--weeks", type=int, default=8, help="how many weeks (default: 8)")
    trend.set_defaults(func=cmd_trend)

    check = subparsers.add_parser(
        "check", help="exit non-zero if any active project has not reported"
    )
    check.add_argument("--week")
    check.set_defaults(func=cmd_check)

    export = subparsers.add_parser("export", help="dump all entries")
    export.add_argument("--format", choices=("csv", "json"), default="csv")
    export.add_argument("--project")
    export.add_argument("--out", metavar="FILE")
    export.set_defaults(func=cmd_export)

    return parser


# ------------------------------------------------------------- commands ---
def cmd_project_add(args, store: Store) -> int:
    project = store.add_project(Project.create(args.slug, args.name, args.owner))
    store.save()
    print(f"Tracking {project.slug} ({project.name}).")
    return 0


def cmd_project_list(args, store: Store) -> int:
    projects = store.projects(include_archived=args.all)
    if not projects:
        print("No projects yet. Add one with: wfb project add <id>")
        return 0
    width = max(len(p.slug) for p in projects)
    current = wk.current_week()
    for project in projects:
        entry = store.get_entry(project.slug, current)
        mark = STATUS_ICONS[entry.status] if entry else "  "
        flags = " [archived]" if project.archived else ""
        owner = f"  owner: {project.owner}" if project.owner else ""
        state = "reported" if entry else "not reported"
        print(f"{mark} {project.slug:<{width}}  {project.name}{owner}  ({state}){flags}")
    print(f"\n{len(projects)} project(s); status shown for {current}.")
    return 0


def cmd_project_archive(args, store: Store) -> int:
    project = store.set_archived(args.slug, True)
    store.save()
    print(f"Archived {project.slug}; it will no longer be expected in weekly reports.")
    return 0


def cmd_project_restore(args, store: Store) -> int:
    project = store.set_archived(args.slug, False)
    store.save()
    print(f"Restored {project.slug}.")
    return 0


def cmd_project_rm(args, store: Store) -> int:
    slug = store.require_project(args.slug).slug
    entries = store.entries(project=slug)
    if entries and not args.with_entries:
        raise ValidationError(
            f"{slug} still has {len(entries)} feedback entr"
            f"{'y' if len(entries) == 1 else 'ies'}; "
            "pass --with-entries to delete them too, or archive the project instead"
        )
    removed = store.remove_project(slug, drop_entries=args.with_entries)
    store.save()
    suffix = f" and {removed} entr{'y' if removed == 1 else 'ies'}" if removed else ""
    print(f"Deleted {slug}{suffix}.")
    return 0


def cmd_submit(args, store: Store) -> int:
    project = store.require_project(args.slug)
    week = wk.parse(args.week)

    # An --append that doesn't name a status must not quietly reset a red week
    # back to the green default.
    existing = store.get_entry(project.slug, week)
    inherited = existing.status if (args.append and existing) else "green"

    fields = {
        "status": args.status or inherited,
        "author": args.author,
        "rating": args.rating,
        "highlights": list(args.highlight),
        "lowlights": list(args.lowlight),
        "blockers": list(args.blocker),
        "next_steps": list(args.next_steps),
        "notes": args.note,
    }
    if args.interactive:
        fields = _prompt_fields(project, week, fields)

    entry = Entry.create(project=project.slug, week=week, **fields)
    if entry.is_empty:
        raise ValidationError(
            "nothing to record; add at least one --highlight/--lowlight/"
            "--blocker/--next/--note, or use --interactive"
        )

    mode = "append" if args.append else "replace" if args.replace else "error"
    stored = store.put_entry(entry, mode=mode)
    store.save()
    verb = {"append": "Added to", "replace": "Replaced", "error": "Recorded"}[mode]
    print(
        f"{verb} feedback for {project.slug} in {week} "
        f"({STATUS_ICONS[stored.status]} {stored.status})."
    )
    return 0


def cmd_show(args, store: Store) -> int:
    project = store.require_project(args.slug)
    week = wk.parse(args.week)
    entry = store.get_entry(project.slug, week)
    if entry is None:
        print(f"No feedback for {project.slug} in {week}.")
        return 1
    if args.json:
        print(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False))
        return 0
    digest = reporting.build(store, week, project=project.slug)
    print(reporting.render_text(digest), end="")
    return 0


def cmd_list(args, store: Store) -> int:
    week = wk.parse(args.week) if args.week else None
    status = normalize_status(args.status) if args.status else None
    if args.project:
        store.require_project(args.project)
    entries = store.entries(project=args.project, week=week, status=status)
    if not entries:
        print("No matching feedback entries.")
        return 0
    width = max(len(entry.project) for entry in entries)
    for entry in entries:
        rating = f"{entry.rating}/5" if entry.rating is not None else "  -"
        author = f"  {entry.author}" if entry.author else ""
        headline = (
            entry.highlights[0] if entry.highlights
            else entry.blockers[0] if entry.blockers
            else entry.notes.splitlines()[0] if entry.notes
            else ""
        )
        print(
            f"{entry.week}  {STATUS_ICONS[entry.status]} {entry.project:<{width}}  "
            f"{rating}{author}  {headline}".rstrip()
        )
    print(f"\n{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}.")
    return 0


def cmd_rm(args, store: Store) -> int:
    project = store.require_project(args.slug)
    week = wk.parse(args.week)
    if not store.delete_entry(project.slug, week):
        print(f"No feedback for {project.slug} in {week}.")
        return 1
    store.save()
    print(f"Deleted feedback for {project.slug} in {week}.")
    return 0


def cmd_report(args, store: Store) -> int:
    week = wk.parse(args.week)
    digest = reporting.build(store, week, project=args.project)
    if args.format == "json":
        text = json.dumps(digest.to_dict(), indent=2, ensure_ascii=False) + "\n"
    elif args.format == "text":
        text = reporting.render_text(digest)
    else:
        text = reporting.render_markdown(digest)
    _emit(text, args.out)
    return 0


def cmd_trend(args, store: Store) -> int:
    if args.weeks < 1:
        raise ValidationError("--weeks must be at least 1")
    last = wk.parse(args.week)
    week_keys = wk.recent_weeks(last, args.weeks)
    projects = [store.require_project(args.slug)] if args.slug else store.projects()
    if not projects:
        print("No projects to chart yet.")
        return 0
    width = max(len(p.slug) for p in projects)
    print(f"{week_keys[0]} .. {week_keys[-1]}   (+ on track, ~ at risk, ! off track, . no report)")
    print()
    for project in projects:
        print(reporting.render_trend(store, project, week_keys, width=width))
    return 0


def cmd_check(args, store: Store) -> int:
    week = wk.parse(args.week)
    digest = reporting.build(store, week)
    if not digest.expected:
        print("No active projects to check.")
        return 0
    if digest.missing:
        names = ", ".join(project.slug for project in digest.missing)
        print(
            f"{len(digest.missing)} of {digest.expected} project(s) have not "
            f"reported for {week}: {names}"
        )
        return 1
    print(f"All {digest.expected} active project(s) reported for {week}.")
    return 0


def cmd_export(args, store: Store) -> int:
    if args.project:
        store.require_project(args.project)
    entries = store.entries(project=args.project)
    if args.format == "json":
        text = json.dumps(
            [entry.to_dict() for entry in entries], indent=2, ensure_ascii=False
        ) + "\n"
    else:
        buffer = io.StringIO()
        columns = [
            "week", "project", "status", "rating", "author",
            "highlights", "lowlights", "blockers", "next_steps",
            "notes", "created_at", "updated_at",
        ]
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for entry in entries:
            row = entry.to_dict()
            for key in ("highlights", "lowlights", "blockers", "next_steps"):
                row[key] = " | ".join(row[key])
            row["rating"] = "" if row["rating"] is None else row["rating"]
            writer.writerow({column: row[column] for column in columns})
        text = buffer.getvalue()
    _emit(text, args.out)
    return 0


# --------------------------------------------------------------- helpers ---
def _emit(text: str, out: str | None) -> None:
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Wrote {out}.")
    else:
        sys.stdout.write(text)


def _needs_subcommand(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 2


def _prompt_fields(project: Project, week: str, fields: dict) -> dict:
    """Ask for each field on the terminal, keeping any values already passed."""
    print(f"Weekly feedback for {project.name} - {week}")
    print("(blank keeps the current value; enter list items one per line, blank to end)\n")

    status = input(f"status [{fields['status']}]: ").strip()
    if status:
        fields["status"] = status
    author = input(f"author [{fields['author'] or '-'}]: ").strip()
    if author:
        fields["author"] = author
    rating = input("rating 1-5 [skip]: ").strip()
    if rating:
        fields["rating"] = rating
    for key, label in (
        ("highlights", "Highlights"),
        ("lowlights", "Lowlights"),
        ("blockers", "Blockers"),
        ("next_steps", "Next week"),
    ):
        print(f"\n{label}:")
        fields[key] = list(fields[key]) + _prompt_list()
    note = input("\nnotes: ").strip()
    if note:
        fields["notes"] = "\n".join(part for part in (fields["notes"], note) if part)
    return fields


def _prompt_list() -> list[str]:
    items: list[str] = []
    while True:
        try:
            line = input("  - ").strip()
        except EOFError:
            break
        if not line:
            break
        items.append(line)
    return items


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    store = Store(args.data)
    try:
        store.load()
        return args.func(args, store)
    except (ValidationError, wk.WeekError, StorageError) as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("\nAborted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
