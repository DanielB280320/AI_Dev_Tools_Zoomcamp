import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weekly_feedback import feedback, health, report
from weekly_feedback.gitstats import RS, US, Activity, Snapshot, Window, parse_log

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
WINDOW = Window(start=NOW - timedelta(days=7), end=NOW)


def make(name, commits, paths, dirty=()):
    raw = "".join(
        RS
        + US.join([sha, "Ada", "ada@example.com", (NOW - timedelta(days=day)).isoformat(), "", subject])
        + "\n5\t1\tsrc/a.py"
        for sha, day, subject in commits
    )
    snap = Snapshot(
        root=Path(f"/tmp/{name}"),
        name=name,
        branch="main",
        tracked_files=list(paths),
        dirty_files=list(dirty),
        total_commits=len(commits) + 5,
        first_commit=NOW - timedelta(days=40),
        last_commit=NOW - timedelta(days=1),
        has_remote=True,
    )
    return feedback.build(
        name=name,
        path=Path(f"/tmp/{name}"),
        window=WINDOW,
        snapshot=snap,
        current=Activity(window=WINDOW, commits=parse_log(raw)),
        previous=Activity(window=WINDOW),
        health=health.evaluate(paths, size_of=lambda rel: 2000),
        now=NOW,
    )


GOOD = make(
    "alpha",
    [("a", 5, "feat: add loader"), ("b", 3, "test: cover loader"), ("c", 1, "fix: guard nulls")],
    ["README.md", "LICENSE", ".gitignore", "pyproject.toml", "tests/test_a.py", "tests/test_b.py"],
)
BARE = make("beta", [], ["main.py"], dirty=["main.py"])


class MarkdownTests(unittest.TestCase):
    def test_contains_headings_and_sections(self):
        text = report.render([GOOD], fmt="markdown", generated_at=NOW)
        self.assertIn("# Weekly project feedback", text)
        self.assertIn(f"## alpha — grade {GOOD.grade}", text)
        self.assertIn("### What went well", text)
        self.assertIn("### Suggested next steps", text)
        self.assertIn("### Project health checklist", text)

    def test_checklist_marks_pass_and_fail(self):
        text = report.render([GOOD], fmt="md", generated_at=NOW)
        self.assertIn("- [x] README at the project root", text)
        self.assertIn("- [ ] Continuous integration", text)

    def test_summary_table_only_for_multiple_projects(self):
        single = report.render([GOOD], fmt="md", generated_at=NOW)
        self.assertNotIn("| Project | Grade |", single)
        multi = report.render([GOOD, BARE], fmt="md", generated_at=NOW)
        self.assertIn("| Project | Grade |", multi)
        self.assertIn("| alpha |", multi)
        self.assertIn("| beta |", multi)

    def test_summary_table_is_ordered_by_score(self):
        text = report.render([BARE, GOOD], fmt="md", generated_at=NOW)
        rows = [line for line in text.splitlines() if line.startswith("| ") and "/100" in line]
        self.assertTrue(rows[0].startswith("| alpha"))

    def test_next_steps_are_numbered(self):
        text = report.render([BARE], fmt="md", generated_at=NOW)
        block = text.split("### Suggested next steps")[1]
        self.assertTrue(block.strip().startswith("1. "))

    def test_empty_report_is_still_valid(self):
        text = report.render([], fmt="md", generated_at=NOW)
        self.assertIn("No projects were analysed", text)

    def test_ends_with_single_newline(self):
        text = report.render([GOOD], fmt="md", generated_at=NOW)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))


class TextTests(unittest.TestCase):
    def test_plain_output_has_no_ansi_by_default(self):
        text = report.render([GOOD], fmt="text", generated_at=NOW)
        self.assertNotIn("\033[", text)
        self.assertIn("alpha", text)
        self.assertIn("next steps", text)

    def test_color_can_be_enabled(self):
        text = report.render([GOOD], fmt="text", generated_at=NOW, color=True)
        self.assertIn("\033[", text)

    def test_only_failing_checks_are_listed(self):
        text = report.render([GOOD], fmt="text", generated_at=NOW)
        self.assertIn("Continuous integration", text)
        self.assertNotIn("[x] README", text)


class JsonTests(unittest.TestCase):
    def test_payload_shape(self):
        payload = json.loads(report.render([GOOD, BARE], fmt="json", generated_at=NOW))
        self.assertEqual(payload["project_count"], 2)
        self.assertEqual([p["name"] for p in payload["projects"]], ["alpha", "beta"])
        alpha = payload["projects"][0]
        self.assertEqual(alpha["activity"]["commits"], 3)
        self.assertIn("grade", alpha)
        self.assertIn("checks", alpha["health"])

    def test_generated_at_is_recorded(self):
        payload = json.loads(report.render([GOOD], fmt="json", generated_at=NOW))
        self.assertTrue(payload["generated_at"].startswith("2026-09-02"))


class DispatchTests(unittest.TestCase):
    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            report.render([GOOD], fmt="pdf")

    def test_aliases(self):
        self.assertEqual(
            report.render([GOOD], fmt="md", generated_at=NOW),
            report.render([GOOD], fmt="MARKDOWN", generated_at=NOW),
        )


if __name__ == "__main__":
    unittest.main()
