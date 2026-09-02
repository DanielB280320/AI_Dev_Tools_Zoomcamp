"""Build and render the weekly digest."""

from __future__ import annotations

from dataclasses import dataclass

from . import weeks as wk
from .models import STATUS_ICONS, STATUS_MARKS, STATUSES, Entry, Project
from .storage import Store

SECTIONS = (
    ("highlights", "Highlights"),
    ("lowlights", "Lowlights"),
    ("blockers", "Blockers"),
    ("next_steps", "Next"),
)


@dataclass
class ReportRow:
    project: Project
    entry: Entry


@dataclass
class WeeklyReport:
    week: str
    rows: list[ReportRow]
    missing: list[Project]

    @property
    def reported(self) -> int:
        return len(self.rows)

    @property
    def expected(self) -> int:
        return len(self.rows) + len(self.missing)

    @property
    def coverage(self) -> float:
        return (self.reported / self.expected * 100) if self.expected else 0.0

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for row in self.rows:
            counts[row.entry.status] += 1
        return counts

    @property
    def average_rating(self) -> float | None:
        ratings = [row.entry.rating for row in self.rows if row.entry.rating is not None]
        return sum(ratings) / len(ratings) if ratings else None

    @property
    def all_blockers(self) -> list[tuple[Project, str]]:
        return [
            (row.project, blocker)
            for row in self.rows
            for blocker in row.entry.blockers
        ]

    def to_dict(self) -> dict:
        return {
            "week": self.week,
            "range": wk.week_range_label(self.week),
            "coverage": {
                "reported": self.reported,
                "expected": self.expected,
                "percent": round(self.coverage, 1),
            },
            "status_counts": self.status_counts,
            "average_rating": (
                round(self.average_rating, 2) if self.average_rating is not None else None
            ),
            "entries": [
                dict(row.entry.to_dict(), project_name=row.project.name)
                for row in self.rows
            ],
            "missing": [
                {"slug": p.slug, "name": p.name, "owner": p.owner} for p in self.missing
            ],
        }


def build(store: Store, week: str, project: str | None = None) -> WeeklyReport:
    """Assemble the report for ``week``, optionally narrowed to one project."""
    if project:
        candidates = [store.require_project(project)]
    else:
        candidates = store.projects()

    rows: list[ReportRow] = []
    missing: list[Project] = []
    for proj in candidates:
        entry = store.get_entry(proj.slug, week)
        if entry is None:
            missing.append(proj)
        else:
            rows.append(ReportRow(project=proj, entry=entry))

    # Worst status first so whatever needs attention leads the digest.
    order = {status: index for index, status in enumerate(reversed(STATUSES))}
    rows.sort(key=lambda row: (order[row.entry.status], row.project.slug))
    return WeeklyReport(week=week, rows=rows, missing=missing)


# ------------------------------------------------------------- renderers ---
def render_markdown(report: WeeklyReport) -> str:
    out: list[str] = [
        f"# Weekly feedback - {report.week}",
        "",
        f"_{wk.week_range_label(report.week)}_",
        "",
        f"- **Coverage:** {report.reported}/{report.expected} projects reported "
        f"({report.coverage:.0f}%)",
        f"- **Status:** {_status_summary(report, icons=True)}",
    ]
    if report.average_rating is not None:
        out.append(f"- **Average rating:** {report.average_rating:.1f} / 5")
    out.append("")

    if not report.rows:
        out.append("_No feedback submitted for this week yet._")
        out.append("")

    for row in report.rows:
        entry = row.entry
        heading = f"## {STATUS_ICONS[entry.status]} {row.project.name}"
        if row.project.name != row.project.slug:
            heading += f" (`{row.project.slug}`)"
        out.append(heading)
        meta = [f"status **{entry.status}**"]
        if entry.rating is not None:
            meta.append(f"rating **{entry.rating}/5**")
        if entry.author:
            meta.append(f"by _{entry.author}_")
        out.append(" · ".join(meta))
        out.append("")
        for attribute, title in SECTIONS:
            items = getattr(entry, attribute)
            if items:
                out.append(f"**{title}**")
                out.extend(f"- {item}" for item in items)
                out.append("")
        if entry.notes:
            out.extend(f"> {line}" for line in entry.notes.splitlines())
            out.append("")

    if report.missing:
        out.append("## Not reported")
        for project in report.missing:
            owner = f" - owner: {project.owner}" if project.owner else ""
            out.append(f"- `{project.slug}`{owner}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_text(report: WeeklyReport) -> str:
    title = f"Weekly feedback - {report.week}  ({wk.week_range_label(report.week)})"
    out = [title, "=" * len(title), ""]
    out.append(
        f"Coverage: {report.reported}/{report.expected} projects "
        f"({report.coverage:.0f}%)   Status: {_status_summary(report, icons=False)}"
    )
    if report.average_rating is not None:
        out.append(f"Average rating: {report.average_rating:.1f}/5")
    out.append("")

    if not report.rows:
        out.append("No feedback submitted for this week yet.")
        out.append("")

    for row in report.rows:
        entry = row.entry
        bits = [f"[{entry.status}]", row.project.name]
        if entry.rating is not None:
            bits.append(f"{entry.rating}/5")
        if entry.author:
            bits.append(f"({entry.author})")
        out.append(" ".join(bits))
        for attribute, label in SECTIONS:
            for item in getattr(entry, attribute):
                out.append(f"    {label[:4].lower():<5} {item}")
        for line in entry.notes.splitlines():
            out.append(f"    note  {line}")
        out.append("")

    if report.missing:
        out.append("Not reported:")
        for project in report.missing:
            owner = f"  (owner: {project.owner})" if project.owner else ""
            out.append(f"  - {project.slug}{owner}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_trend(
    store: Store, project: Project, week_keys: list[str], width: int = 9
) -> str:
    """One line per project history: a status strip plus the rating sparkline."""
    entries = store.history(project.slug, week_keys)
    strip = "".join(
        STATUS_MARKS[entry.status] if entry is not None else "." for entry in entries
    )
    bars = "".join(_spark(entry.rating if entry else None) for entry in entries)
    ratings = [e.rating for e in entries if e is not None and e.rating is not None]
    average = f"{sum(ratings) / len(ratings):.1f}" if ratings else "  -"
    reported = sum(1 for entry in entries if entry is not None)
    return (
        f"{project.slug:<{width}} {strip}  {bars}  avg {average}  "
        f"{reported}/{len(week_keys)} weeks"
    )


def _spark(rating: int | None) -> str:
    if rating is None:
        return " "
    return "▁▃▅▆█"[rating - 1]


def _status_summary(report: WeeklyReport, icons: bool) -> str:
    counts = report.status_counts
    marker = STATUS_ICONS if icons else {s: s for s in STATUSES}
    return " · ".join(f"{marker[status]} {counts[status]}" for status in STATUSES)
