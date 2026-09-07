import unittest

from weekly_feedback import health


def score_for(paths, sizes=None):
    sizes = sizes or {}
    return health.evaluate(paths, size_of=lambda rel: sizes.get(rel, 100))


class HealthTests(unittest.TestCase):
    def test_empty_project_scores_only_the_absence_checks(self):
        report = score_for([])
        # secrets + large files pass vacuously; everything else is missing.
        self.assertEqual({c.id for c in report.strengths}, {"secrets", "large_files"})
        self.assertLess(report.score, 30)

    def test_complete_project_scores_full_marks(self):
        paths = [
            "README.md",
            "LICENSE",
            ".gitignore",
            "pyproject.toml",
            "Dockerfile",
            ".github/workflows/ci.yml",
            "docs/design.md",
            "tests/test_a.py",
            "tests/test_b.py",
            "src/app.py",
        ]
        report = score_for(paths, sizes={"README.md": 2000})
        self.assertEqual(report.score, 100)
        self.assertEqual(report.gaps, [])

    def test_short_readme_scores_partial(self):
        report = score_for(["README.md"], sizes={"README.md": 40})
        readme = next(c for c in report.checks if c.id == "readme")
        self.assertTrue(readme.partial)
        self.assertIn("40 bytes", readme.detail)

    def test_readme_case_insensitive_and_extensionless(self):
        for name in ("README", "readme.md", "Readme.rst"):
            with self.subTest(name=name):
                report = score_for([name], sizes={name: 2000})
                readme = next(c for c in report.checks if c.id == "readme")
                self.assertTrue(readme.passed)

    def test_nested_readme_does_not_count(self):
        report = score_for(["docs/README.md"], sizes={"docs/README.md": 2000})
        readme = next(c for c in report.checks if c.id == "readme")
        self.assertFalse(readme.passed)

    def test_committed_env_file_fails_the_secrets_check(self):
        report = score_for(["README.md", ".env"])
        secrets = next(c for c in report.checks if c.id == "secrets")
        self.assertFalse(secrets.passed)
        self.assertEqual(secrets.detail, ".env")

    def test_env_example_is_allowed(self):
        report = score_for([".env.example", "config/.env.sample"])
        secrets = next(c for c in report.checks if c.id == "secrets")
        self.assertTrue(secrets.passed)

    def test_single_test_file_is_partial_credit(self):
        report = score_for(["test_only.py"])
        tests = next(c for c in report.checks if c.id == "tests")
        self.assertTrue(tests.partial)

    def test_test_directory_counts(self):
        report = score_for(["tests/unit/test_a.py", "tests/unit/test_b.py"])
        tests = next(c for c in report.checks if c.id == "tests")
        self.assertTrue(tests.passed)

    def test_large_file_is_flagged(self):
        report = score_for(["data/train.csv"], sizes={"data/train.csv": 20 * 1024 * 1024})
        check = next(c for c in report.checks if c.id == "large_files")
        self.assertFalse(check.passed)
        self.assertIn("20 MB", check.detail)

    def test_gaps_are_ordered_by_lost_weight(self):
        report = score_for(["LICENSE"])
        weights = [c.weight for c in report.gaps]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_every_gap_carries_advice(self):
        report = score_for([])
        for check in report.gaps:
            self.assertTrue(check.advice, f"{check.id} has no advice")

    def test_windows_style_paths_are_normalised(self):
        report = health.evaluate([".github\\workflows\\ci.yml"], size_of=lambda rel: 10)
        ci = next(c for c in report.checks if c.id == "ci")
        self.assertTrue(ci.passed)


if __name__ == "__main__":
    unittest.main()
