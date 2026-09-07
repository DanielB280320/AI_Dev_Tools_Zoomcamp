"""Helpers for building throwaway git repositories in tests."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.com",
}


def git(root: Path, *args: str, when: datetime | None = None) -> str:
    env = dict(ENV)
    if when is not None:
        stamp = when.isoformat()
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout


def init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test Author")
    git(root, "config", "user.email", "author@example.com")
    return root


def commit(root: Path, message: str, files: dict[str, str], when: datetime) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message, when=when)


def build_active_repo(root: Path, end: datetime) -> Path:
    """A repo with commits on four separate days inside the last week."""
    init_repo(root)
    commit(
        root,
        "feat: add ingestion pipeline",
        {
            "README.md": "# Project\n\n" + ("Detailed description of the project. " * 30),
            "pipeline.py": "def run():\n    return 1\n",
            ".gitignore": "__pycache__/\n",
        },
        when=end - timedelta(days=6),
    )
    commit(
        root,
        "test: cover the pipeline",
        {"tests/test_pipeline.py": "def test_run():\n    assert True\n"},
        when=end - timedelta(days=4),
    )
    commit(
        root,
        "docs: describe the data model",
        {"docs/design.md": "# Design\n", "requirements.txt": "requests\n"},
        when=end - timedelta(days=2),
    )
    commit(
        root,
        "fix: handle empty payloads",
        {"pipeline.py": "def run(payload=None):\n    return payload or []\n"},
        when=end - timedelta(days=1),
    )
    return root
