"""Turn raw activity + health data into readable weekly feedback."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from weekly_feedback.gitstats import Activity, Snapshot, Window
from weekly_feedback.health import HealthReport

BIG_COMMIT_LINES = 600
MANY_DIRTY_FILES = 8
GRADES = ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F"))

# Activity carries 40% of the weekly score, project health the remaining 60%.
ACTIVITY_WEIGHT = 0.4


@dataclass
class ProjectFeedback:
    name: str
    path: Path
    window: Window
    snapshot: Snapshot
    current: Activity
    previous: Activity
    health: HealthReport
    highlights: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    @property
    def activity_score(self) -> int:
        """0-100 from commit volume, cadence and message quality."""
        commits = self.current.count
        volume = min(commits / 8, 1.0) * 45
        cadence = min(self.current.active_days / 4, 1.0) * 35
        if commits:
            vague = len(self.current.vague_subjects)
            quality = max(0.0, 1.0 - vague / max(commits, 1)) * 20
        else:
            quality = 0.0
        return round(volume + cadence + quality)

    @property
    def score(self) -> int:
        blended = ACTIVITY_WEIGHT * self.activity_score + (1 - ACTIVITY_WEIGHT) * self.health.score
        return round(blended)

    @property
    def grade(self) -> str:
        for threshold, letter in GRADES:
            if self.score >= threshold:
                return letter
        return "F"

    @property
    def commit_delta(self) -> int:
        return self.current.count - self.previous.count

    @property
    def trend(self) -> str:
        delta = self.commit_delta
        if delta > 0:
            return "up"
        if delta < 0:
            return "down"
        return "flat"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "window": {
                "start": self.window.start.isoformat(),
                "end": self.window.end.isoformat(),
                "days": self.window.days,
            },
            "branch": self.snapshot.branch,
            "score": self.score,
            "grade": self.grade,
            "activity_score": self.activity_score,
            "health_score": self.health.score,
            "trend": self.trend,
            "activity": {
                "commits": self.current.count,
                "commits_previous_window": self.previous.count,
                "active_days": self.current.active_days,
                "insertions": self.current.insertions,
                "deletions": self.current.deletions,
                "files_touched": self.current.files_touched,
                "authors": self.current.authors,
                "merges": self.current.merges,
                "median_commit_churn": self.current.median_commit_churn,
                "conventional_ratio": round(self.current.conventional_ratio, 2),
                "vague_subjects": self.current.vague_subjects,
            },
            "repository": {
                "total_commits": self.snapshot.total_commits,
                "tracked_files": len(self.snapshot.tracked_files),
                "uncommitted_files": len(self.snapshot.dirty_files),
                "has_remote": self.snapshot.has_remote,
                "last_commit": self.snapshot.last_commit.isoformat()
                if self.snapshot.last_commit
                else None,
            },
            "health": {
                "score": self.health.score,
                "points": round(self.health.points, 2),
                "max_points": self.health.max_points,
                "checks": [
                    {
                        "id": c.id,
                        "label": c.label,
                        "status": c.symbol,
                        "weight": c.weight,
                        "detail": c.detail,
                        "advice": c.advice,
                    }
                    for c in self.health.checks
                ],
            },
            "highlights": self.highlights,
            "concerns": self.concerns,
            "next_steps": self.next_steps,
        }


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def build(
    name: str,
    path: Path,
    window: Window,
    snapshot: Snapshot,
    current: Activity,
    previous: Activity,
    health: HealthReport,
    now: datetime | None = None,
) -> ProjectFeedback:
    """Assemble the narrative parts of the report."""
    fb = ProjectFeedback(
        name=name,
        path=path,
        window=window,
        snapshot=snapshot,
        current=current,
        previous=previous,
        health=health,
    )
    _narrate_activity(fb, now=now)
    _narrate_health(fb)
    _narrate_hygiene(fb)
    if not fb.highlights:
        fb.highlights.append("Nothing stood out this week — the notes below are where to start.")
    return fb


def _narrate_activity(fb: ProjectFeedback, now: datetime | None) -> None:
    cur, prev = fb.current, fb.previous
    days = fb.window.days

    if cur.count == 0:
        last = fb.snapshot.last_commit
        if last is not None:
            reference = now or fb.window.end
            if reference.tzinfo is None and last.tzinfo is not None:
                reference = reference.replace(tzinfo=last.tzinfo)
            idle = (reference - last).days
            fb.concerns.append(
                f"No commits in the last {days} days — last activity was {idle} days ago "
                f"({last:%Y-%m-%d})."
            )
        else:
            fb.concerns.append("The repository has no commits yet.")
        fb.next_steps.append("Land one small commit to restart momentum, even if it is only notes or scaffolding.")
        return

    summary = (
        f"{_plural(cur.count, 'commit')} across {_plural(cur.active_days, 'active day')}, "
        f"+{cur.insertions}/-{cur.deletions} over {_plural(cur.files_touched, 'file')}."
    )
    fb.highlights.append(summary)

    if prev.count and cur.count >= 2 * prev.count:
        fb.highlights.append(f"Output more than doubled week over week ({prev.count} to {cur.count} commits).")
    elif prev.count and cur.count <= prev.count / 2:
        fb.concerns.append(
            f"Commit volume dropped sharply ({prev.count} to {cur.count} commits versus the previous {days} days)."
        )

    if cur.active_days >= max(3, days // 2):
        fb.highlights.append(f"Steady cadence: work landed on {cur.active_days} separate days rather than one push.")
    elif cur.count >= 3 and cur.active_days == 1:
        busiest = cur.busiest_day
        day = busiest[0] if busiest else "a single day"
        fb.concerns.append(f"All {cur.count} commits landed on {day}; the work is batched into one session.")
        fb.next_steps.append("Commit as you go rather than in one batch — it makes progress reviewable.")

    if len(cur.authors) > 1:
        fb.highlights.append(f"{len(cur.authors)} contributors: {', '.join(cur.authors[:4])}.")

    largest = cur.largest_commit
    if largest is not None and largest.churn > BIG_COMMIT_LINES:
        fb.concerns.append(
            f"One commit changed {largest.churn} lines ({largest.sha[:7]} \"{largest.subject}\") — hard to review."
        )
        fb.next_steps.append("Split large changes into commits that each do one thing.")

    vague = cur.vague_subjects
    if vague:
        sample = ", ".join(f'"{s}"' for s in vague[:3])
        verb = "says" if len(vague) == 1 else "say"
        fb.concerns.append(
            f"{_plural(len(vague), 'commit message')} {verb} little about the change: {sample}."
        )
        fb.next_steps.append(
            "Write commit subjects as an imperative summary of the change, e.g. \"add ingestion retry on 429\"."
        )
    elif cur.conventional_ratio >= 0.8:
        fb.highlights.append("Commit messages follow a consistent conventional format.")

    if cur.merges and cur.merges == cur.count:
        fb.concerns.append("Every commit in the window is a merge — no direct work landed on this branch.")


def _narrate_health(fb: ProjectFeedback) -> None:
    strengths = [c.label for c in fb.health.strengths]
    if len(strengths) >= 3:
        fb.highlights.append("Project hygiene in place: " + ", ".join(strengths[:4]).lower() + ".")

    for check in fb.health.gaps:
        if check.id == "secrets":
            fb.concerns.insert(0, f"Credential-shaped files are committed to git: {check.detail}.")
        else:
            fb.concerns.append(f"{check.label}: {check.detail}.")
        if check.advice:
            fb.next_steps.append(check.advice)


def _narrate_hygiene(fb: ProjectFeedback) -> None:
    dirty = len(fb.snapshot.dirty_files)
    if dirty >= MANY_DIRTY_FILES:
        fb.concerns.append(f"{_plural(dirty, 'file')} are uncommitted in the working tree.")
        fb.next_steps.append("Commit or stash the working tree so the repository reflects the real state of the project.")
    if not fb.snapshot.has_remote:
        fb.concerns.append("No git remote is configured — the work only exists on this machine.")
        fb.next_steps.append("Push the repository to a remote so it is backed up and reviewable.")

    # Deduplicate while preserving order.
    for attr in ("highlights", "concerns", "next_steps"):
        seen: set[str] = set()
        unique = []
        for item in getattr(fb, attr):
            if item not in seen:
                seen.add(item)
                unique.append(item)
        setattr(fb, attr, unique)
