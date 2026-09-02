"""Rubric-style project health checks driven by the tracked file list."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

LARGE_FILE_BYTES = 5 * 1024 * 1024

SECRET_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_dsa",
    "id_ed25519",
    "*credentials*.json",
    "*service-account*.json",
    "*.keystore",
)

_SECRET_ALLOWED = ("*.env.example", "*.env.sample", "*.env.template", ".env.example")

TEST_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "*_test.go",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.ts",
    "*Test.java",
    "*_spec.rb",
)

DEPENDENCY_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "environment.yml",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Gemfile",
)

CI_PATHS = (
    ".github/workflows/*",
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    "Jenkinsfile",
    ".travis.yml",
)

CONTAINER_FILES = (
    "Dockerfile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
    "Containerfile",
)


@dataclass
class Check:
    """One rubric line item, scored between 0.0 and 1.0."""

    id: str
    label: str
    weight: int
    score: float
    detail: str
    advice: str = ""

    @property
    def passed(self) -> bool:
        return self.score >= 0.999

    @property
    def partial(self) -> bool:
        return 0.0 < self.score < 0.999

    @property
    def symbol(self) -> str:
        if self.passed:
            return "pass"
        if self.partial:
            return "partial"
        return "missing"

    @property
    def earned(self) -> float:
        return self.weight * self.score


@dataclass
class HealthReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def max_points(self) -> int:
        return sum(c.weight for c in self.checks)

    @property
    def points(self) -> float:
        return sum(c.earned for c in self.checks)

    @property
    def score(self) -> int:
        if not self.max_points:
            return 0
        return round(100 * self.points / self.max_points)

    @property
    def gaps(self) -> list[Check]:
        """Unmet checks, most valuable first."""
        unmet = [c for c in self.checks if not c.passed]
        return sorted(unmet, key=lambda c: (-c.weight * (1 - c.score), c.id))

    @property
    def strengths(self) -> list[Check]:
        return [c for c in self.checks if c.passed]


def _matches(paths: Sequence[str], patterns: Sequence[str]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        base = path.rsplit("/", 1)[-1]
        for pattern in patterns:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(base, pattern):
                hits.append(path)
                break
    return hits


def _root_level(paths: Sequence[str]) -> list[str]:
    return [p for p in paths if "/" not in p]


def _read_size(root: Path | None, rel: str) -> int:
    if root is None:
        return 0
    try:
        return (root / rel).stat().st_size
    except OSError:
        return 0


def evaluate(
    tracked: Sequence[str],
    root: Path | None = None,
    size_of: Callable[[str], int] | None = None,
) -> HealthReport:
    """Score a project from its tracked file list.

    ``root`` is optional so the rubric stays testable without a real checkout;
    when omitted, size-based checks fall back to "no evidence of a problem".
    """
    paths = [p.replace("\\", "/") for p in tracked]
    sizer = size_of or (lambda rel: _read_size(root, rel))
    checks: list[Check] = [
        _check_readme(paths, sizer),
        _check_tests(paths),
        _check_secrets(paths),
        _check_dependencies(paths),
        _check_ci(paths),
        _check_gitignore(paths),
        _check_docs(paths),
        _check_container(paths),
        _check_license(paths),
        _check_large_files(paths, sizer),
    ]
    return HealthReport(checks=checks)


def _check_readme(paths: Sequence[str], sizer: Callable[[str], int]) -> Check:
    readmes = [p for p in _root_level(paths) if re.match(r"readme(\.|$)", p, re.IGNORECASE)]
    if not readmes:
        return Check(
            "readme",
            "README at the project root",
            weight=3,
            score=0.0,
            detail="no README found",
            advice="Add a README covering what the project does, how to run it, and what the data is.",
        )
    size = max(sizer(p) for p in readmes)
    if size and size < 400:
        return Check(
            "readme",
            "README at the project root",
            weight=3,
            score=0.5,
            detail=f"{readmes[0]} is only {size} bytes",
            advice="Expand the README: problem statement, setup steps, how to reproduce your results.",
        )
    return Check("readme", "README at the project root", weight=3, score=1.0, detail=readmes[0])


def _check_tests(paths: Sequence[str]) -> Check:
    hits = _matches(paths, TEST_PATTERNS)
    dirs = [p for p in paths if re.match(r"(^|.*/)(tests?)/", p)]
    found = sorted(set(hits) | set(dirs))
    if not found:
        return Check(
            "tests",
            "Automated tests",
            weight=3,
            score=0.0,
            detail="no test files detected",
            advice="Add at least a smoke test for the main entry point; it is the cheapest regression guard.",
        )
    if len(found) < 2:
        return Check(
            "tests",
            "Automated tests",
            weight=3,
            score=0.6,
            detail=f"1 test file ({found[0]})",
            advice="Broaden test coverage beyond the single existing test file.",
        )
    return Check("tests", "Automated tests", weight=3, score=1.0, detail=f"{len(found)} test files")


def _check_secrets(paths: Sequence[str]) -> Check:
    hits = [
        p
        for p in _matches(paths, SECRET_PATTERNS)
        if not _matches([p], _SECRET_ALLOWED)
    ]
    if hits:
        listed = ", ".join(hits[:3]) + (", ..." if len(hits) > 3 else "")
        return Check(
            "secrets",
            "No credential-shaped files committed",
            weight=3,
            score=0.0,
            detail=listed,
            advice=(
                "Remove the credential-shaped files from version control, rotate anything "
                "they contained, and add the pattern to .gitignore."
            ),
        )
    return Check(
        "secrets",
        "No credential-shaped files committed",
        weight=3,
        score=1.0,
        detail="clean",
    )


def _check_dependencies(paths: Sequence[str]) -> Check:
    hits = _matches(_root_level(paths), DEPENDENCY_FILES)
    if not hits:
        return Check(
            "dependencies",
            "Declared dependencies",
            weight=2,
            score=0.0,
            detail="no manifest at the root",
            advice="Pin dependencies in requirements.txt or pyproject.toml so a reviewer can reproduce your environment.",
        )
    return Check("dependencies", "Declared dependencies", weight=2, score=1.0, detail=hits[0])


def _check_ci(paths: Sequence[str]) -> Check:
    hits = _matches(paths, CI_PATHS)
    if not hits:
        return Check(
            "ci",
            "Continuous integration",
            weight=2,
            score=0.0,
            detail="no CI configuration",
            advice="Add a GitHub Actions workflow that installs deps and runs the tests on every push.",
        )
    return Check("ci", "Continuous integration", weight=2, score=1.0, detail=hits[0])


def _check_gitignore(paths: Sequence[str]) -> Check:
    if ".gitignore" in paths:
        return Check("gitignore", ".gitignore present", weight=1, score=1.0, detail=".gitignore")
    return Check(
        "gitignore",
        ".gitignore present",
        weight=1,
        score=0.0,
        detail="missing",
        advice="Add a .gitignore so build output, virtualenvs and local config stay out of history.",
    )


def _check_docs(paths: Sequence[str]) -> Check:
    docs_dir = [p for p in paths if p.startswith("docs/")]
    markdown = [p for p in paths if p.lower().endswith(".md")]
    if docs_dir or len(markdown) >= 3:
        detail = f"{len(docs_dir)} files under docs/" if docs_dir else f"{len(markdown)} markdown files"
        return Check("docs", "Documentation beyond the README", weight=1, score=1.0, detail=detail)
    return Check(
        "docs",
        "Documentation beyond the README",
        weight=1,
        score=0.0,
        detail="README only",
        advice="Document your architecture or data flow in docs/ so reviewers can follow the design.",
    )


def _check_container(paths: Sequence[str]) -> Check:
    hits = _matches(_root_level(paths), CONTAINER_FILES)
    if hits:
        return Check("container", "Reproducible runtime (Docker)", weight=1, score=1.0, detail=hits[0])
    return Check(
        "container",
        "Reproducible runtime (Docker)",
        weight=1,
        score=0.0,
        detail="no Dockerfile or compose file",
        advice="A small Dockerfile makes the project runnable by anyone reviewing it.",
    )


def _check_license(paths: Sequence[str]) -> Check:
    hits = [p for p in _root_level(paths) if re.match(r"(license|licence|copying)(\.|$)", p, re.IGNORECASE)]
    if hits:
        return Check("license", "License file", weight=1, score=1.0, detail=hits[0])
    return Check(
        "license",
        "License file",
        weight=1,
        score=0.0,
        detail="missing",
        advice="Add a LICENSE so others know the terms for reusing the project.",
    )


def _check_large_files(paths: Sequence[str], sizer: Callable[[str], int]) -> Check:
    offenders = [(p, sizer(p)) for p in paths]
    offenders = [(p, s) for p, s in offenders if s > LARGE_FILE_BYTES]
    if offenders:
        worst = max(offenders, key=lambda kv: kv[1])
        return Check(
            "large_files",
            "No oversized files in git history",
            weight=1,
            score=0.0,
            detail=f"{len(offenders)} file(s) over 5 MB, largest {worst[0]} ({worst[1] // (1024 * 1024)} MB)",
            advice="Move large data out of git (DVC, object storage, or a download script).",
        )
    return Check(
        "large_files",
        "No oversized files in git history",
        weight=1,
        score=1.0,
        detail="all tracked files under 5 MB",
    )
