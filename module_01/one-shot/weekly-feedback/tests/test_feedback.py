import unittest
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weekly_feedback import feedback, health
from weekly_feedback.gitstats import RS, US, Activity, Snapshot, Window, parse_log

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
WINDOW = Window(start=NOW - timedelta(days=7), end=NOW)
PREVIOUS = Window(start=NOW - timedelta(days=14), end=NOW - timedelta(days=7))

GOOD_PATHS = [
    "README.md",
    "LICENSE",
    ".gitignore",
    "pyproject.toml",
    "Dockerfile",
    ".github/workflows/ci.yml",
    "docs/design.md",
    "tests/test_a.py",
    "tests/test_b.py",
]


def make_commit(sha, author, day, subject, added=5, removed=1, path="src/a.py"):
    when = (NOW - timedelta(days=day)).isoformat()
    header = RS + US.join([sha, author, f"{author}@example.com", when, "", subject])
    return "\n".join([header, f"{added}\t{removed}\t{path}"])


def activity(specs, window=WINDOW):
    return Activity(window=window, commits=parse_log("".join(make_commit(*s) for s in specs)))


def snapshot(**overrides):
    defaults = dict(
        root=Path("/tmp/proj"),
        name="proj",
        branch="main",
        tracked_files=list(GOOD_PATHS),
        dirty_files=[],
        total_commits=20,
        first_commit=NOW - timedelta(days=60),
        last_commit=NOW - timedelta(days=1),
        has_remote=True,
    )
    defaults.update(overrides)
    return Snapshot(**defaults)


def build(current=None, previous=None, snap=None, paths=None, sizes=None):
    snap = snap or snapshot()
    paths = GOOD_PATHS if paths is None else paths
    sizes = sizes or {}
    rubric = health.evaluate(paths, size_of=lambda rel: sizes.get(rel, 2000))
    return feedback.build(
        name="proj",
        path=Path("/tmp/proj"),
        window=WINDOW,
        snapshot=snap,
        current=current if current is not None else activity([]),
        previous=previous if previous is not None else Activity(window=PREVIOUS),
        health=rubric,
        now=NOW,
    )


class ScoringTests(unittest.TestCase):
    def test_healthy_and_active_project_scores_high(self):
        fb = build(current=activity([
            ("a", "Ada", 6, "feat: add loader"),
            ("b", "Ada", 5, "feat: add parser"),
            ("c", "Ada", 3, "test: cover parser"),
            ("d", "Ada", 2, "docs: explain the schema"),
            ("e", "Ada", 1, "fix: handle blank rows"),
            ("f", "Ada", 1, "refactor: extract helper"),
            ("g", "Ada", 0, "chore: bump deps"),
            ("h", "Ada", 0, "feat: add export"),
        ]))
        self.assertEqual(fb.health.score, 100)
        self.assertEqual(fb.activity_score, 100)
        self.assertEqual(fb.score, 100)
        self.assertEqual(fb.grade, "A")

    def test_idle_and_bare_project_scores_low(self):
        fb = build(paths=[], snap=snapshot(tracked_files=[], last_commit=NOW - timedelta(days=30)))
        self.assertEqual(fb.activity_score, 0)
        self.assertLess(fb.score, 30)
        self.assertEqual(fb.grade, "F")

    def test_score_blends_activity_and_health(self):
        fb = build(current=activity([("a", "Ada", 1, "feat: add loader")]))
        expected = round(0.4 * fb.activity_score + 0.6 * fb.health.score)
        self.assertEqual(fb.score, expected)

    def test_grade_boundaries(self):
        class Fixed(feedback.ProjectFeedback):
            forced = 0

            @property
            def score(self):
                return self.forced

        fb = build()
        graded = Fixed(**{f.name: getattr(fb, f.name) for f in fields(fb)})
        for score, grade in ((100, "A"), (90, "A"), (89, "B"), (80, "B"), (79, "C"),
                             (70, "C"), (69, "D"), (60, "D"), (59, "F"), (0, "F")):
            with self.subTest(score=score):
                graded.forced = score
                self.assertEqual(graded.grade, grade)


class NarrativeTests(unittest.TestCase):
    def test_idle_project_reports_days_since_last_commit(self):
        fb = build(snap=snapshot(last_commit=NOW - timedelta(days=21)))
        self.assertTrue(any("No commits in the last 7 days" in c for c in fb.concerns))
        self.assertTrue(any("21 days ago" in c for c in fb.concerns))
        self.assertTrue(fb.next_steps)

    def test_repository_without_commits_is_called_out(self):
        fb = build(snap=snapshot(last_commit=None, total_commits=0))
        self.assertIn("The repository has no commits yet.", fb.concerns)

    def test_activity_summary_is_a_highlight(self):
        fb = build(current=activity([("a", "Ada", 1, "feat: add loader", 10, 2)]))
        self.assertTrue(any("+10/-2" in h for h in fb.highlights))

    def test_batched_work_is_flagged(self):
        fb = build(current=activity([
            ("a", "Ada", 1, "feat: add loader"),
            ("b", "Ada", 1, "feat: add parser"),
            ("c", "Ada", 1, "feat: add writer"),
        ]))
        self.assertTrue(any("landed on" in c and "one session" in c for c in fb.concerns))

    def test_steady_cadence_is_praised(self):
        fb = build(current=activity([
            ("a", "Ada", 5, "feat: add loader"),
            ("b", "Ada", 3, "feat: add parser"),
            ("c", "Ada", 1, "feat: add writer"),
        ]))
        self.assertTrue(any("Steady cadence" in h for h in fb.highlights))

    def test_vague_messages_are_reported_with_examples(self):
        fb = build(current=activity([
            ("a", "Ada", 3, "update"),
            ("b", "Ada", 2, "wip"),
            ("c", "Ada", 1, "feat: add writer"),
        ]))
        concern = next(c for c in fb.concerns if "say little" in c)
        self.assertIn('"update"', concern)
        self.assertIn('"wip"', concern)

    def test_oversized_commit_is_reported(self):
        fb = build(current=activity([("a", "Ada", 1, "feat: rewrite", 900, 200)]))
        self.assertTrue(any("changed 1100 lines" in c for c in fb.concerns))
        self.assertTrue(any("Split large changes" in s for s in fb.next_steps))

    def test_growth_versus_previous_window_is_a_highlight(self):
        current = activity([("a", "Ada", i, f"feat: step {i}") for i in range(6)])
        previous = activity([("z", "Ada", 8, "feat: old")], window=PREVIOUS)
        fb = build(current=current, previous=previous)
        self.assertTrue(any("more than doubled" in h for h in fb.highlights))
        self.assertEqual(fb.trend, "up")
        self.assertEqual(fb.commit_delta, 5)

    def test_drop_versus_previous_window_is_a_concern(self):
        current = activity([("a", "Ada", 1, "feat: step")])
        previous = activity([("z", "Ada", 8 + i, f"feat: old {i}") for i in range(6)], window=PREVIOUS)
        fb = build(current=current, previous=previous)
        self.assertTrue(any("dropped sharply" in c for c in fb.concerns))
        self.assertEqual(fb.trend, "down")

    def test_multiple_contributors_are_highlighted(self):
        fb = build(current=activity([
            ("a", "Ada", 2, "feat: add loader"),
            ("b", "Linus", 1, "feat: add parser"),
        ]))
        self.assertTrue(any("2 contributors" in h for h in fb.highlights))

    def test_health_gaps_become_next_steps(self):
        fb = build(paths=["main.py"], snap=snapshot(tracked_files=["main.py"]))
        self.assertTrue(any("README" in s for s in fb.next_steps))
        self.assertTrue(any("smoke test" in s for s in fb.next_steps))

    def test_committed_secret_is_the_first_concern(self):
        paths = GOOD_PATHS + [".env"]
        fb = build(paths=paths, snap=snapshot(tracked_files=paths))
        self.assertEqual(fb.concerns[0], "Credential-shaped files are committed to git: .env.")

    def test_dirty_worktree_is_flagged(self):
        fb = build(snap=snapshot(dirty_files=[f"f{i}.py" for i in range(10)]))
        self.assertTrue(any("uncommitted" in c for c in fb.concerns))

    def test_missing_remote_is_flagged(self):
        fb = build(snap=snapshot(has_remote=False))
        self.assertTrue(any("No git remote" in c for c in fb.concerns))

    def test_sections_are_deduplicated(self):
        fb = build(paths=[], snap=snapshot(tracked_files=[], has_remote=False))
        for section in (fb.highlights, fb.concerns, fb.next_steps):
            self.assertEqual(len(section), len(set(section)))

    def test_highlights_are_never_empty(self):
        fb = build(paths=[], snap=snapshot(tracked_files=[], last_commit=NOW - timedelta(days=40)))
        self.assertTrue(fb.highlights)


class SerialisationTests(unittest.TestCase):
    def test_as_dict_is_json_ready(self):
        import json

        fb = build(current=activity([("a", "Ada", 1, "feat: add loader")]))
        payload = json.loads(json.dumps(fb.as_dict()))
        self.assertEqual(payload["name"], "proj")
        self.assertEqual(payload["activity"]["commits"], 1)
        self.assertEqual(payload["health"]["max_points"], fb.health.max_points)
        self.assertEqual(len(payload["health"]["checks"]), len(fb.health.checks))
        self.assertIn("next_steps", payload)


if __name__ == "__main__":
    unittest.main()
