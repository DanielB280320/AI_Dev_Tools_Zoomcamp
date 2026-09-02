import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.helpers import build_active_repo, commit, init_repo
from weekly_feedback import cli

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
END = "2026-09-02T12:00:00+00:00"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class WindowTests(unittest.TestCase):
    def test_windows_are_adjacent_and_equal_length(self):
        current, previous = cli.make_windows(NOW, 7)
        self.assertEqual(current.end, NOW)
        self.assertEqual(previous.end, current.start)
        self.assertEqual(current.days, previous.days)

    def test_end_date_rolls_to_end_of_day(self):
        end = cli.parse_end("2026-09-02")
        self.assertEqual(end.date().isoformat(), "2026-09-02")
        self.assertEqual((end.hour, end.minute), (23, 59))

    def test_end_accepts_full_timestamp(self):
        self.assertEqual(cli.parse_end(END).isoformat(), END)

    def test_bad_end_date_is_rejected(self):
        with self.assertRaises(SystemExit):
            cli.parse_end("last tuesday")


class NormalizeTests(unittest.TestCase):
    def test_bare_path_gets_the_report_subcommand(self):
        self.assertEqual(cli.normalize(["/tmp/x"]), ["report", "/tmp/x"])

    def test_bare_flags_get_the_report_subcommand(self):
        self.assertEqual(cli.normalize(["--days", "3"]), ["report", "--days", "3"])

    def test_explicit_subcommands_are_untouched(self):
        self.assertEqual(cli.normalize(["init"]), ["init"])
        self.assertEqual(cli.normalize(["report", "--days", "3"]), ["report", "--days", "3"])

    def test_help_is_untouched(self):
        self.assertEqual(cli.normalize(["--help"]), ["--help"])

    def test_no_arguments_defaults_to_report(self):
        self.assertEqual(cli.normalize([]), ["report"])


class ReportCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.repo = build_active_repo(self.dir / "alpha", NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown_report_for_one_repository(self):
        code, out, _ = run(str(self.repo), "--end", END, "--no-config")
        self.assertEqual(code, 0)
        self.assertIn("# Weekly project feedback", out)
        self.assertIn("## alpha", out)
        self.assertIn("4 commits", out)

    def test_json_report_is_machine_readable(self):
        code, out, _ = run(str(self.repo), "--end", END, "--format", "json", "--no-config")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        project = payload["projects"][0]
        self.assertEqual(project["name"], "alpha")
        self.assertEqual(project["activity"]["commits"], 4)
        self.assertEqual(project["activity"]["active_days"], 4)
        self.assertEqual(project["branch"], "main")

    def test_text_report_has_no_ansi_when_not_a_tty(self):
        code, out, _ = run(str(self.repo), "--end", END, "--format", "text", "--no-config")
        self.assertEqual(code, 0)
        self.assertNotIn("\033[", out)

    def test_days_narrows_the_window(self):
        code, out, _ = run(str(self.repo), "--end", END, "--days", "3", "--format", "json", "--no-config")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["projects"][0]["activity"]["commits"], 2)

    def test_out_writes_a_file(self):
        target = self.dir / "reports" / "week.md"
        code, out, _ = run(str(self.repo), "--end", END, "--no-config", "--out", str(target))
        self.assertEqual(code, 0)
        self.assertTrue(target.is_file())
        self.assertIn("Weekly project feedback", target.read_text(encoding="utf-8"))
        self.assertIn("wrote", out)

    def test_scan_picks_up_every_repository(self):
        build_active_repo(self.dir / "beta", NOW)
        (self.dir / "not-a-repo").mkdir()
        code, out, _ = run("--scan", str(self.dir), "--end", END, "--format", "json", "--no-config")
        self.assertEqual(code, 0)
        names = {p["name"] for p in json.loads(out)["projects"]}
        self.assertEqual(names, {"alpha", "beta"})

    def test_duplicate_paths_are_reported_once(self):
        code, out, _ = run(str(self.repo), str(self.repo / "docs"), "--end", END,
                           "--format", "json", "--no-config")
        self.assertEqual(json.loads(out)["project_count"], 1)

    def test_non_repository_is_skipped_with_a_warning(self):
        plain = self.dir / "plain"
        plain.mkdir()
        code, _, err = run(str(self.repo), str(plain), "--end", END, "--format", "json", "--no-config")
        self.assertEqual(code, 0)
        self.assertIn("skipping", err)

    def test_no_repositories_is_an_error(self):
        plain = self.dir / "plain"
        plain.mkdir()
        code, _, err = run(str(plain), "--end", END, "--no-config")
        self.assertEqual(code, 2)
        self.assertIn("no git repositories", err)

    def test_fail_under_sets_the_exit_code(self):
        code, _, err = run(str(self.repo), "--end", END, "--no-config", "--fail-under", "100")
        self.assertEqual(code, 1)
        self.assertIn("below --fail-under", err)

    def test_fail_under_passes_when_score_is_high_enough(self):
        code, _, _ = run(str(self.repo), "--end", END, "--no-config", "--fail-under", "1")
        self.assertEqual(code, 0)

    def test_zero_days_is_rejected(self):
        code, _, err = run(str(self.repo), "--days", "0", "--no-config")
        self.assertEqual(code, 2)
        self.assertIn("--days", err)

    def test_idle_repository_still_reports(self):
        idle = init_repo(self.dir / "idle")
        commit(idle, "initial", {"main.py": "print(1)\n"}, when=NOW - timedelta(days=40))
        code, out, _ = run(str(idle), "--end", END, "--no-config", "--format", "json")
        self.assertEqual(code, 0)
        project = json.loads(out)["projects"][0]
        self.assertEqual(project["activity"]["commits"], 0)
        self.assertTrue(any("No commits" in c for c in project["concerns"]))

    def test_config_file_supplies_the_project_list(self):
        cfg = self.dir / "weekly-feedback.toml"
        cfg.write_text(
            f'[defaults]\ndays = 7\nformat = "json"\n\n[[projects]]\nname = "renamed"\npath = "{self.repo}"\n',
            encoding="utf-8",
        )
        code, out, _ = run("--config", str(cfg), "--end", END)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["projects"][0]["name"], "renamed")

    def test_command_line_overrides_config_format(self):
        cfg = self.dir / "weekly-feedback.toml"
        cfg.write_text(f'[defaults]\nformat = "json"\n\n[[projects]]\npath = "{self.repo}"\n', encoding="utf-8")
        code, out, _ = run("--config", str(cfg), "--end", END, "--format", "md")
        self.assertEqual(code, 0)
        self.assertIn("# Weekly project feedback", out)

    def test_broken_config_is_reported(self):
        cfg = self.dir / "broken.toml"
        cfg.write_text("nope = = 1", encoding="utf-8")
        code, _, err = run("--config", str(cfg), "--end", END)
        self.assertEqual(code, 2)
        self.assertIn("could not parse", err)


class InitCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_a_sample_config(self):
        target = self.dir / "weekly-feedback.toml"
        code, out, _ = run("init", "--out", str(target))
        self.assertEqual(code, 0)
        self.assertTrue(target.is_file())
        self.assertIn("[defaults]", target.read_text(encoding="utf-8"))
        self.assertIn("wrote", out)

    def test_refuses_to_overwrite(self):
        target = self.dir / "weekly-feedback.toml"
        target.write_text("keep me", encoding="utf-8")
        code, _, err = run("init", "--out", str(target))
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep me")

    def test_force_overwrites(self):
        target = self.dir / "weekly-feedback.toml"
        target.write_text("keep me", encoding="utf-8")
        code, _, _ = run("init", "--out", str(target), "--force")
        self.assertEqual(code, 0)
        self.assertIn("[defaults]", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
