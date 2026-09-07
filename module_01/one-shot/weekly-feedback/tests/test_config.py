import json
import tempfile
import unittest
from pathlib import Path

from weekly_feedback import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_loads_toml(self):
        path = self.write(
            "weekly-feedback.toml",
            '[defaults]\ndays = 14\nformat = "text"\nfail_under = 70\n\n'
            '[[projects]]\nname = "capstone"\npath = "repos/capstone"\n',
        )
        cfg = config.load(path)
        self.assertEqual(cfg.days, 14)
        self.assertEqual(cfg.format, "text")
        self.assertEqual(cfg.fail_under, 70)
        self.assertEqual(cfg.projects[0].name, "capstone")
        self.assertTrue(cfg.projects[0].path.is_absolute())
        self.assertTrue(str(cfg.projects[0].path).endswith("repos/capstone"))

    def test_loads_json(self):
        path = self.write(
            "weekly-feedback.json",
            json.dumps({"defaults": {"days": 3}, "projects": [{"path": "a"}]}),
        )
        cfg = config.load(path)
        self.assertEqual(cfg.days, 3)
        self.assertEqual(cfg.projects[0].name, "a")

    def test_plain_string_projects(self):
        cfg = config.from_mapping({"projects": ["/tmp/one", "/tmp/two"]})
        self.assertEqual([p.name for p in cfg.projects], ["one", "two"])

    def test_project_without_path_is_rejected(self):
        with self.assertRaises(config.ConfigError):
            config.from_mapping({"projects": [{"name": "x"}]})

    def test_malformed_file_is_rejected(self):
        path = self.write("weekly-feedback.toml", "this is not = = toml")
        with self.assertRaises(config.ConfigError):
            config.load(path)

    def test_missing_file_is_rejected(self):
        with self.assertRaises(config.ConfigError):
            config.load(self.dir / "nope.toml")

    def test_defaults_when_empty(self):
        cfg = config.from_mapping({})
        self.assertEqual(cfg.days, 7)
        self.assertEqual(cfg.format, "markdown")
        self.assertEqual(cfg.projects, [])

    def test_scan_paths_are_resolved(self):
        path = self.write("weekly-feedback.toml", '[defaults]\nscan = ["workspace"]\n')
        cfg = config.load(path)
        self.assertEqual(cfg.scan[0].name, "workspace")
        self.assertTrue(cfg.scan[0].is_absolute())

    def test_find_config_walks_up_the_tree(self):
        self.write("weekly-feedback.toml", "[defaults]\ndays = 5\n")
        nested = self.dir / "a" / "b"
        nested.mkdir(parents=True)
        found = config.find_config(nested)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "weekly-feedback.toml")

    def test_sample_config_is_parseable(self):
        path = self.write("weekly-feedback.toml", config.SAMPLE_CONFIG)
        cfg = config.load(path)
        self.assertEqual(cfg.days, 7)
        self.assertEqual(len(cfg.projects), 1)


if __name__ == "__main__":
    unittest.main()
