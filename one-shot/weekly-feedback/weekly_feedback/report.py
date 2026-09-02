"""Render weekly feedback as Markdown, terminal text, or JSON."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Sequence

from weekly_feedback.feedback import ProjectFeedback

STATUS_MARK = {"pass": "[x]", "partial": "[~]", "missing": "[ ]"}

_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
}


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _paint(text: str, *styles: str, enabled: bool = True) -> str:
    if not enabled or not styles:
        return text
    prefix = "".join(_ANSI[s] for s in styles if s in _ANSI)
    return f"{prefix}{text}{_ANSI['reset']}"


def _grade_style(grade: str) -> str:
    return {"A": "green", "B": "green", "C": "yellow", "D": "yellow"}.get(grade, "red")


def _trend_phrase(fb: ProjectFeedback) -> str:
    delta = fb.commit_delta
    if delta == 0:
        return f"same as the previous window ({fb.previous.count})"
    direction = "up" if delta > 0 else "down"
    return f"{direction} {abs(delta)} vs the previous window ({fb.previous.count})"


def render(
    reports: Sequence[ProjectFeedback],
    fmt: str = "markdown",
    generated_at: datetime | None = None,
    color: bool = False,
) -> str:
    fmt = fmt.lower()
    if fmt in {"json"}:
        return render_json(reports, generated_at=generated_at)
    if fmt in {"text", "term", "terminal"}:
        return render_text(reports, generated_at=generated_at, color=color)
    if fmt in {"markdown", "md"}:
        return render_markdown(reports, generated_at=generated_at)
    raise ValueError(f"unknown format: {fmt}")


def render_json(reports: Sequence[ProjectFeedback], generated_at: datetime | None = None) -> str:
    payload = {
        "generated_at": (generated_at or datetime.now()).isoformat(timespec="seconds"),
        "project_count": len(reports),
        "projects": [r.as_dict() for r in reports],
    }
    return json.dumps(payload, indent=2)


def render_markdown(reports: Sequence[ProjectFeedback], generated_at: datetime | None = None) -> str:
    stamp = generated_at or datetime.now()
    lines: list[str] = ["# Weekly project feedback", ""]
    if reports:
        window = reports[0].window
        lines.append(f"Window: **{window.label()}** ({window.days} days)  ")
    lines.append(f"Generated: {stamp:%Y-%m-%d %H:%M}")
    lines.append("")

    if not reports:
        lines.append("_No projects were analysed._")
        return "\n".join(lines) + "\n"

    if len(reports) > 1:
        lines.append("| Project | Grade | Score | Commits | Active days | Churn | Health |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in sorted(reports, key=lambda x: -x.score):
            lines.append(
                f"| {r.name} | {r.grade} | {r.score}/100 | {r.current.count} "
                f"({_signed(r.commit_delta)}) | {r.current.active_days} | "
                f"+{r.current.insertions}/-{r.current.deletions} | {r.health.score}/100 |"
            )
        lines.append("")

    for report in reports:
        lines.extend(_markdown_project(report))
    return "\n".join(lines).rstrip() + "\n"


def _signed(value: int) -> str:
    return f"{value:+d}" if value else "0"


def _markdown_project(fb: ProjectFeedback) -> list[str]:
    lines = [
        f"## {fb.name} — grade {fb.grade} ({fb.score}/100)",
        "",
        f"`{fb.path}` on branch `{fb.snapshot.branch}`",
        "",
        f"- **Activity:** {_plural(fb.current.count, 'commit')}, {_trend_phrase(fb)}; "
        f"{_plural(fb.current.active_days, 'active day')}; "
        f"+{fb.current.insertions}/-{fb.current.deletions} "
        f"across {_plural(fb.current.files_touched, 'file')}",
        f"- **Contributors:** {', '.join(fb.current.authors) or 'none this window'}",
        f"- **Scores:** activity {fb.activity_score}/100, health {fb.health.score}/100 "
        f"({fb.health.points:g} of {fb.health.max_points} rubric points)",
        f"- **Repository:** {fb.snapshot.total_commits} commits total, "
        f"{len(fb.snapshot.tracked_files)} tracked files, "
        f"{len(fb.snapshot.dirty_files)} uncommitted",
        "",
    ]

    lines.extend(_markdown_section("What went well", fb.highlights))
    lines.extend(_markdown_section("Needs attention", fb.concerns))
    lines.extend(_markdown_section("Suggested next steps", fb.next_steps, numbered=True))

    lines.append("### Project health checklist")
    lines.append("")
    for check in fb.health.checks:
        mark = STATUS_MARK[check.symbol]
        detail = f" — {check.detail}" if check.detail else ""
        lines.append(f"- {mark} {check.label} ({check.weight} pt){detail}")
    lines.append("")
    return lines


def _markdown_section(title: str, items: Sequence[str], numbered: bool = False) -> list[str]:
    if not items:
        return []
    lines = [f"### {title}", ""]
    for index, item in enumerate(items, start=1):
        prefix = f"{index}." if numbered else "-"
        lines.append(f"{prefix} {item}")
    lines.append("")
    return lines


def render_text(
    reports: Sequence[ProjectFeedback],
    generated_at: datetime | None = None,
    color: bool = False,
) -> str:
    stamp = generated_at or datetime.now()
    out: list[str] = []
    header = "WEEKLY PROJECT FEEDBACK"
    out.append(_paint(header, "bold", enabled=color))
    if reports:
        out.append(_paint(f"window {reports[0].window.label()}  ·  generated {stamp:%Y-%m-%d %H:%M}", "dim", enabled=color))
    out.append("")

    if not reports:
        out.append("No projects were analysed.")
        return "\n".join(out) + "\n"

    for fb in reports:
        title = f"{fb.name}  [{fb.grade}] {fb.score}/100"
        out.append(_paint(title, "bold", _grade_style(fb.grade), enabled=color))
        out.append(_paint(f"  {fb.path} ({fb.snapshot.branch})", "dim", enabled=color))
        out.append(
            f"  {_plural(fb.current.count, 'commit')} · {_plural(fb.current.active_days, 'active day')} · "
            f"+{fb.current.insertions}/-{fb.current.deletions} · "
            f"{_trend_phrase(fb)}"
        )
        out.append(f"  activity {fb.activity_score}/100 · health {fb.health.score}/100")
        out.append("")
        _text_section(out, "went well", fb.highlights, "green", color)
        _text_section(out, "needs attention", fb.concerns, "yellow", color)
        _text_section(out, "next steps", fb.next_steps, "cyan", color)
        failed = [c for c in fb.health.checks if not c.passed]
        if failed:
            out.append(_paint("  checklist gaps", "bold", enabled=color))
            for check in failed:
                out.append(f"    {STATUS_MARK[check.symbol]} {check.label} ({check.weight} pt) — {check.detail}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _text_section(out: list[str], title: str, items: Sequence[str], style: str, color: bool) -> None:
    if not items:
        return
    out.append(_paint(f"  {title}", "bold", style, enabled=color))
    for item in items:
        out.append(f"    - {item}")
    out.append("")
