import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import build_active_repo, commit, git, init_repo
from weekly_feedback import gitstats
from weekly_feedback.gitstats import RS, US, Window

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def log_line(sha, author, iso, parents, subject, numstat=()):
    header = RS + US.join([sha, author, f"{author}@example.com", iso, parents, subject])
    return "\n".join([header, *numstat])


class ParseLogTests(unittest.TestCase):
    def test_parses_header_and_numstat(self):
        raw = log_line(
            "abc123", "Ada", "2026-09-01T10:00:00+00:00", "def456", "feat: add thing",
            numstat=["10\t2\tsrc/a.py", "3\t0\tsrc/b.py"],
        )
        (commit_obj,) = gitstats.parse_log(raw)
        self.assertEqual(commit_obj.sha, "abc123")
        self.assertEqual(commit_obj.author, "Ada")
        self.assertEqual(commit_obj.insertions, 13)
        self.assertEqual(commit_obj.deletions, 2)
        self.assertEqual(commit_obj.files, ("src/a.py", "src/b.py"))
        self.assertFalse(commit_obj.is_merge)
        self.assertTrue(commit_obj.is_conventional)

    def test_binary_numstat_dashes_are_ignored(self):
        raw = log_line("a", "Ada", "2026-09-01T10:00:00+00:00", "", "add image", ["-\t-\tlogo.png"])
        (commit_obj,) = gitstats.parse_log(raw)
        self.assertEqual(commit_obj.churn, 0)
        self.assertEqual(commit_obj.files, ("logo.png",))

    def test_merge_detected_from_multiple_parents(self):
        raw = log_line("a", "Ada", "2026-09-01T10:00:00+00:00", "p1 p2", "Merge branch 'x'")
        (commit_obj,) = gitstats.parse_log(raw)
        self.assertTrue(commit_obj.is_merge)

    def test_empty_output_yields_no_commits(self):
        self.assertEqual(gitstats.parse_log(""), [])

    def test_subject_containing_tabs_is_kept(self):
        raw = log_line("a", "Ada", "2026-09-01T10:00:00+00:00", "", "fix: trim\ttabs")
        (commit_obj,) = gitstats.parse_log(raw)
        self.assertEqual(commit_obj.subject, "fix: trim\ttabs")


class CommitQualityTests(unittest.TestCase):
    def make(self, subject):
        raw = log_line("a", "Ada", "2026-09-01T10:00:00+00:00", "", subject)
        return gitstats.parse_log(raw)[0]

    def test_vague_subjects(self):
        for subject in ("update", "WIP", "Commit changes", "fix", "."):
            with self.subTest(subject=subject):
                self.assertTrue(self.make(subject).is_vague)

    def test_descriptive_subjects_are_not_vague(self):
        for subject in ("feat: add retry on 429", "Rework the ingestion loop"):
            with self.subTest(subject=subject):
                self.assertFalse(self.make(subject).is_vague)

    def test_short_conventional_subject_is_not_vague(self):
        self.assertFalse(self.make("fix: typo").is_vague)


class ActivityTests(unittest.TestCase):
    def setUp(self):
        window = Window(start=NOW - timedelta(days=7), end=NOW)
        raw = "".join(
            [
                log_line("a", "Ada", "2026-09-01T10:00:00+00:00", "", "feat: one", ["10\t1\tx.py"]),
                log_line("b", "Ada", "2026-09-01T18:00:00+00:00", "", "update", ["1\t1\tx.py"]),
                log_line("c", "Linus", "2026-08-30T09:00:00+00:00", "", "fix: two", ["5\t50\ty.py"]),
                log_line("d", "Ada", "2026-08-29T09:00:00+00:00", "p1 p2", "Merge branch 'x'"),
            ]
        )
        self.activity = gitstats.Activity(window=window, commits=gitstats.parse_log(raw))

    def test_aggregates(self):
        a = self.activity
        self.assertEqual(a.count, 4)
        self.assertEqual(a.insertions, 16)
        self.assertEqual(a.deletions, 52)
        self.assertEqual(a.files_touched, 2)
        self.assertEqual(a.merges, 1)
        self.assertEqual(a.active_days, 3)

    def test_authors_ordered_by_commit_count(self):
        self.assertEqual(self.activity.authors, ["Ada", "Linus"])

    def test_largest_commit_ignores_merges(self):
        largest = self.activity.largest_commit
        self.assertEqual(largest.sha, "c")

    def test_vague_subjects_listed(self):
        self.assertEqual(self.activity.vague_subjects, ["update"])

    def test_conventional_ratio_excludes_merges(self):
        self.assertAlmostEqual(self.activity.conventional_ratio, 2 / 3)

    def test_busiest_day(self):
        self.assertEqual(self.activity.busiest_day, ("2026-09-01", 2))

    def test_median_commit_churn(self):
        self.assertEqual(self.activity.median_commit_churn, 11)

    def test_empty_activity_is_safe(self):
        empty = gitstats.Activity(window=self.activity.window)
        self.assertEqual(empty.count, 0)
        self.assertEqual(empty.authors, [])
        self.assertIsNone(empty.largest_commit)
        self.assertIsNone(empty.busiest_day)
        self.assertEqual(empty.conventional_ratio, 0.0)
        self.assertEqual(empty.median_commit_churn, 0)


class WindowTests(unittest.TestCase):
    def test_days_and_label(self):
        window = Window(start=NOW - timedelta(days=7), end=NOW)
        self.assertEqual(window.days, 7)
        self.assertEqual(window.label(), "2026-08-26 to 2026-09-02")


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = build_active_repo(Path(self.tmp.name) / "proj", NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_repo_root_from_subdirectory(self):
        found = gitstats.repo_root(self.root / "docs")
        self.assertEqual(found.resolve(), self.root.resolve())

    def test_non_repo_is_rejected(self):
        outside = Path(self.tmp.name) / "plain"
        outside.mkdir()
        self.assertFalse(gitstats.is_repo(outside))
        with self.assertRaises(gitstats.NotAGitRepository):
            gitstats.repo_root(Path(self.tmp.name) / "missing")

    def test_collect_window_counts_only_commits_inside_it(self):
        recent = gitstats.collect(self.root, Window(NOW - timedelta(days=3), NOW))
        self.assertEqual(recent.count, 2)
        week = gitstats.collect(self.root, Window(NOW - timedelta(days=7), NOW))
        self.assertEqual(week.count, 4)
        self.assertEqual(week.active_days, 4)

    def test_collect_outside_history_is_empty(self):
        old = gitstats.collect(self.root, Window(NOW - timedelta(days=90), NOW - timedelta(days=30)))
        self.assertEqual(old.count, 0)

    def test_snapshot_reports_repository_facts(self):
        snap = gitstats.snapshot(self.root)
        self.assertEqual(snap.branch, "main")
        self.assertEqual(snap.total_commits, 4)
        self.assertIn("README.md", snap.tracked_files)
        self.assertFalse(snap.has_remote)
        self.assertEqual(snap.dirty_files, [])
        self.assertIsNotNone(snap.first_commit)
        self.assertLess(snap.first_commit, snap.last_commit)

    def test_snapshot_sees_uncommitted_files(self):
        (self.root / "scratch.txt").write_text("wip", encoding="utf-8")
        snap = gitstats.snapshot(self.root)
        self.assertIn("scratch.txt", snap.dirty_files)

    def test_snapshot_on_repository_without_commits(self):
        empty = init_repo(Path(self.tmp.name) / "empty")
        snap = gitstats.snapshot(empty)
        self.assertEqual(snap.total_commits, 0)
        self.assertIsNone(snap.last_commit)
        activity = gitstats.collect(empty, Window(NOW - timedelta(days=7), NOW))
        self.assertEqual(activity.count, 0)

    def test_discover_repos_finds_nested_projects(self):
        workspace = Path(self.tmp.name) / "workspace"
        for name in ("alpha", "beta"):
            init_repo(workspace / name)
        (workspace / "notes").mkdir(parents=True, exist_ok=True)
        found = {p.name for p in gitstats.discover_repos(workspace)}
        self.assertEqual(found, {"alpha", "beta"})

    def test_discover_repos_returns_the_directory_itself_when_it_is_a_repo(self):
        self.assertEqual(gitstats.discover_repos(self.root), [self.root])


if __name__ == "__main__":
    unittest.main()
