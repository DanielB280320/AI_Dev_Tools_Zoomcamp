"""Tests for the weekly feedback tool. Run with: python3 -m unittest discover tests"""

import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from weekly_feedback import report as reporting  # noqa: E402
from weekly_feedback import weeks as wk  # noqa: E402
from weekly_feedback.cli import main  # noqa: E402
from weekly_feedback.models import Entry, Project, ValidationError  # noqa: E402
from weekly_feedback.storage import Store, StorageError  # noqa: E402


class WeekTests(unittest.TestCase):
    def test_week_key_and_bounds(self):
        self.assertEqual(wk.week_key(dt.date(2026, 9, 2)), "2026-W36")
        self.assertEqual(wk.week_start("2026-W36"), dt.date(2026, 8, 31))
        self.assertEqual(wk.week_end("2026-W36"), dt.date(2026, 9, 6))

    def test_parse_forms(self):
        today = dt.date(2026, 9, 2)
        self.assertEqual(wk.parse(None, today), "2026-W36")
        self.assertEqual(wk.parse("current", today), "2026-W36")
        self.assertEqual(wk.parse("last", today), "2026-W35")
        self.assertEqual(wk.parse("next", today), "2026-W37")
        self.assertEqual(wk.parse("-3", today), "2026-W33")
        self.assertEqual(wk.parse("2026-W01", today), "2026-W01")
        self.assertEqual(wk.parse("2026W1", today), "2026-W01")
        self.assertEqual(wk.parse("2026-09-06", today), "2026-W36")

    def test_parse_rejects_nonsense(self):
        for bad in ["hello", "2026-W99", "2026-02-30", "W36"]:
            with self.assertRaises(wk.WeekError, msg=bad):
                wk.parse(bad, dt.date(2026, 9, 2))

    def test_shift_crosses_year_boundary(self):
        # 2025 is a 52-week ISO year, so W01 of 2026 is preceded by 2025-W52.
        self.assertEqual(wk.shift("2026-W01", -1), "2025-W52")
        self.assertEqual(wk.recent_weeks("2026-W02", 3), ["2025-W52", "2026-W01", "2026-W02"])
        # 2026 is a 53-week year, so its W53 is real and rolls into 2027-W01.
        self.assertEqual(wk.shift("2026-W53", 1), "2027-W01")

    def test_week_53_on_a_52_week_year_is_rejected(self):
        with self.assertRaises(wk.WeekError):
            wk.week_start("2025-W53")
        with self.assertRaises(wk.WeekError):
            wk.parse("2025-W53", dt.date(2026, 9, 2))


class ModelTests(unittest.TestCase):
    def test_slug_normalisation(self):
        self.assertEqual(Project.create("  Apollo Core ").slug, "apollo-core")
        with self.assertRaises(ValidationError):
            Project.create("-nope")

    def test_status_aliases(self):
        entry = Entry.create("apollo", "2026-W36", status="YELLOW", highlights=["x"])
        self.assertEqual(entry.status, "amber")
        with self.assertRaises(ValidationError):
            Entry.create("apollo", "2026-W36", status="purple")

    def test_rating_bounds(self):
        self.assertIsNone(Entry.create("a", "2026-W36", notes="n").rating)
        self.assertEqual(Entry.create("a", "2026-W36", rating="4", notes="n").rating, 4)
        for bad in ("0", "6", "high"):
            with self.assertRaises(ValidationError):
                Entry.create("a", "2026-W36", rating=bad, notes="n")

    def test_blank_list_items_are_dropped(self):
        entry = Entry.create("a", "2026-W36", highlights=["  shipped  ", "", "   "])
        self.assertEqual(entry.highlights, ["shipped"])

    def test_merge_appends_and_prefers_new_scalars(self):
        first = Entry.create("a", "2026-W36", status="green", author="dana",
                             rating=4, highlights=["one"], notes="start")
        second = Entry.create("a", "2026-W36", status="red", highlights=["two"],
                              notes="more")
        merged = first.merged_with(second)
        self.assertEqual(merged.status, "red")
        self.assertEqual(merged.author, "dana")     # kept: not overridden
        self.assertEqual(merged.rating, 4)          # kept: not overridden
        self.assertEqual(merged.highlights, ["one", "two"])
        self.assertEqual(merged.notes, "start\nmore")
        self.assertEqual(merged.created_at, first.created_at)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "data.json"
        self.store = Store(self.path).load()
        self.addCleanup(self.tmp.cleanup)

    def test_round_trip(self):
        self.store.add_project(Project.create("apollo", "Apollo", "dana"))
        self.store.put_entry(Entry.create("apollo", "2026-W36", highlights=["ship"]))
        self.store.save()

        reloaded = Store(self.path).load()
        self.assertEqual([p.slug for p in reloaded.projects()], ["apollo"])
        entry = reloaded.get_entry("apollo", "2026-W36")
        self.assertEqual(entry.highlights, ["ship"])

    def test_duplicate_project_rejected(self):
        self.store.add_project(Project.create("apollo"))
        with self.assertRaises(ValidationError):
            self.store.add_project(Project.create("apollo"))

    def test_duplicate_entry_modes(self):
        self.store.add_project(Project.create("apollo"))
        self.store.put_entry(Entry.create("apollo", "2026-W36", highlights=["one"]))
        with self.assertRaises(ValidationError):
            self.store.put_entry(Entry.create("apollo", "2026-W36", highlights=["two"]))

        appended = self.store.put_entry(
            Entry.create("apollo", "2026-W36", highlights=["two"]), mode="append"
        )
        self.assertEqual(appended.highlights, ["one", "two"])

        replaced = self.store.put_entry(
            Entry.create("apollo", "2026-W36", highlights=["three"]), mode="replace"
        )
        self.assertEqual(replaced.highlights, ["three"])

    def test_archived_projects_hidden_by_default(self):
        self.store.add_project(Project.create("apollo"))
        self.store.add_project(Project.create("zephyr"))
        self.store.set_archived("zephyr", True)
        self.assertEqual([p.slug for p in self.store.projects()], ["apollo"])
        self.assertEqual(len(self.store.projects(include_archived=True)), 2)

    def test_filters(self):
        for slug in ("apollo", "zephyr"):
            self.store.add_project(Project.create(slug))
        self.store.put_entry(Entry.create("apollo", "2026-W35", status="red", notes="n"))
        self.store.put_entry(Entry.create("apollo", "2026-W36", notes="n"))
        self.store.put_entry(Entry.create("zephyr", "2026-W36", status="amber", notes="n"))

        self.assertEqual(len(self.store.entries(project="apollo")), 2)
        self.assertEqual(len(self.store.entries(week="2026-W36")), 2)
        self.assertEqual(len(self.store.entries(status="red")), 1)
        self.assertEqual(self.store.weeks(), ["2026-W35", "2026-W36"])

    def test_corrupt_file_is_reported(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(StorageError):
            Store(self.path).load()

    def test_newer_schema_is_refused(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 99}), encoding="utf-8")
        with self.assertRaises(StorageError):
            Store(self.path).load()


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "data.json").load()
        self.addCleanup(self.tmp.cleanup)
        for slug in ("apollo", "borealis", "zephyr"):
            self.store.add_project(Project.create(slug, owner="dana"))
        self.store.put_entry(
            Entry.create("apollo", "2026-W36", status="green", rating=5,
                         highlights=["shipped v2"])
        )
        self.store.put_entry(
            Entry.create("borealis", "2026-W36", status="red", rating=2,
                         blockers=["waiting on review"])
        )

    def test_coverage_and_counts(self):
        digest = reporting.build(self.store, "2026-W36")
        self.assertEqual((digest.reported, digest.expected), (2, 3))
        self.assertAlmostEqual(digest.coverage, 66.66666, places=3)
        self.assertEqual(digest.status_counts, {"green": 1, "amber": 0, "red": 1})
        self.assertAlmostEqual(digest.average_rating, 3.5)
        self.assertEqual([p.slug for p in digest.missing], ["zephyr"])

    def test_worst_status_leads(self):
        digest = reporting.build(self.store, "2026-W36")
        self.assertEqual([row.project.slug for row in digest.rows], ["borealis", "apollo"])

    def test_archived_projects_are_not_counted_as_missing(self):
        self.store.set_archived("zephyr", True)
        digest = reporting.build(self.store, "2026-W36")
        self.assertEqual(digest.expected, 2)
        self.assertEqual(digest.missing, [])

    def test_markdown_render(self):
        text = reporting.render_markdown(reporting.build(self.store, "2026-W36"))
        self.assertIn("# Weekly feedback - 2026-W36", text)
        self.assertIn("2/3 projects reported (67%)", text)
        self.assertIn("- shipped v2", text)
        self.assertIn("waiting on review", text)
        self.assertIn("## Not reported", text)

    def test_empty_week_renders(self):
        text = reporting.render_markdown(reporting.build(self.store, "2026-W20"))
        self.assertIn("No feedback submitted for this week yet.", text)

    def test_trend_line(self):
        project = self.store.require_project("apollo")
        line = reporting.render_trend(
            self.store, project, wk.recent_weeks("2026-W36", 3)
        )
        self.assertTrue(line.startswith("apollo"))
        self.assertIn("..+", line)      # two silent weeks then a green one
        self.assertIn("avg 5.0", line)
        self.assertIn("1/3 weeks", line)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = str(Path(self.tmp.name) / "data.json")
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--data", self.data, *argv])
        return code, out.getvalue(), err.getvalue()

    def seed(self):
        self.run_cli("project", "add", "apollo", "--name", "Apollo", "--owner", "dana")
        self.run_cli("project", "add", "zephyr")
        self.run_cli(
            "submit", "apollo", "--week", "2026-W36", "--status", "green",
            "--rating", "4", "--author", "dana", "--highlight", "shipped v2",
            "--blocker", "flaky CI", "--next", "cut the release",
        )

    def test_add_and_list_projects(self):
        code, out, _ = self.run_cli("project", "add", "apollo", "--owner", "dana")
        self.assertEqual(code, 0)
        self.assertIn("Tracking apollo", out)
        code, out, _ = self.run_cli("project", "list")
        self.assertIn("apollo", out)
        self.assertIn("owner: dana", out)

    def test_submit_requires_known_project(self):
        code, _, err = self.run_cli("submit", "ghost", "--note", "hi")
        self.assertEqual(code, 1)
        self.assertIn("no project 'ghost'", err)

    def test_submit_requires_content(self):
        self.run_cli("project", "add", "apollo")
        code, _, err = self.run_cli("submit", "apollo")
        self.assertEqual(code, 1)
        self.assertIn("nothing to record", err)

    def test_submit_duplicate_needs_a_flag(self):
        self.seed()
        code, _, err = self.run_cli(
            "submit", "apollo", "--week", "2026-W36", "--note", "again"
        )
        self.assertEqual(code, 1)
        self.assertIn("--replace", err)

        code, out, _ = self.run_cli(
            "submit", "apollo", "--week", "2026-W36", "--note", "again", "--append"
        )
        self.assertEqual(code, 0)
        self.assertIn("Added to", out)

        code, out, _ = self.run_cli("show", "apollo", "--week", "2026-W36")
        self.assertIn("shipped v2", out)
        self.assertIn("again", out)

    def test_append_keeps_the_existing_status_unless_told_otherwise(self):
        self.run_cli("project", "add", "borealis")
        self.run_cli(
            "submit", "borealis", "--week", "2026-W36", "--status", "red",
            "--blocker", "flaky suite",
        )
        self.run_cli(
            "submit", "borealis", "--week", "2026-W36", "--append",
            "--blocker", "short a reviewer",
        )
        _, out, _ = self.run_cli("show", "borealis", "--week", "2026-W36", "--json")
        entry = json.loads(out)
        self.assertEqual(entry["status"], "red")
        self.assertEqual(entry["blockers"], ["flaky suite", "short a reviewer"])

        # ...but an explicit status on the append still wins.
        self.run_cli(
            "submit", "borealis", "--week", "2026-W36", "--append",
            "--status", "green", "--note", "unblocked",
        )
        _, out, _ = self.run_cli("show", "borealis", "--week", "2026-W36", "--json")
        self.assertEqual(json.loads(out)["status"], "green")

    def test_report_markdown_and_json(self):
        self.seed()
        code, out, _ = self.run_cli("report", "--week", "2026-W36")
        self.assertEqual(code, 0)
        self.assertIn("# Weekly feedback - 2026-W36", out)
        self.assertIn("shipped v2", out)
        self.assertIn("zephyr", out)      # listed as not reported

        code, out, _ = self.run_cli("report", "--week", "2026-W36", "--format", "json")
        payload = json.loads(out)
        self.assertEqual(payload["coverage"], {"reported": 1, "expected": 2, "percent": 50.0})
        self.assertEqual(payload["missing"][0]["slug"], "zephyr")

    def test_report_to_file(self):
        self.seed()
        target = str(Path(self.tmp.name) / "digest.md")
        code, out, _ = self.run_cli("report", "--week", "2026-W36", "--out", target)
        self.assertEqual(code, 0)
        self.assertIn("Wrote", out)
        self.assertIn("Apollo", Path(target).read_text(encoding="utf-8"))

    def test_check_exit_codes(self):
        self.seed()
        code, out, _ = self.run_cli("check", "--week", "2026-W36")
        self.assertEqual(code, 1)
        self.assertIn("zephyr", out)

        self.run_cli("project", "archive", "zephyr")
        code, out, _ = self.run_cli("check", "--week", "2026-W36")
        self.assertEqual(code, 0)
        self.assertIn("All 1 active project(s) reported", out)

    def test_list_and_filters(self):
        self.seed()
        code, out, _ = self.run_cli("list", "--status", "green")
        self.assertEqual(code, 0)
        self.assertIn("apollo", out)
        code, out, _ = self.run_cli("list", "--status", "red")
        self.assertIn("No matching feedback entries.", out)

    def test_export_csv(self):
        self.seed()
        code, out, _ = self.run_cli("export", "--format", "csv")
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertTrue(lines[0].startswith("week,project,status,rating"))
        self.assertIn("shipped v2", lines[1])

    def test_rm_entry_and_project(self):
        self.seed()
        code, _, err = self.run_cli("project", "rm", "apollo")
        self.assertEqual(code, 1)
        self.assertIn("--with-entries", err)

        code, out, _ = self.run_cli("rm", "apollo", "--week", "2026-W36")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("project", "rm", "apollo")
        self.assertEqual(code, 0)
        self.assertIn("Deleted apollo", out)

    def test_trend_renders_all_projects(self):
        self.seed()
        code, out, _ = self.run_cli("trend", "--week", "2026-W36", "--weeks", "4")
        self.assertEqual(code, 0)
        self.assertIn("apollo", out)
        self.assertIn("zephyr", out)
        self.assertIn("2026-W33 .. 2026-W36", out)

    def test_bad_week_is_a_clean_error(self):
        self.run_cli("project", "add", "apollo")
        code, _, err = self.run_cli("submit", "apollo", "--week", "soon", "--note", "x")
        self.assertEqual(code, 1)
        self.assertIn("cannot read week", err)

    def test_no_command_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()
