"""Collect git activity for a project over a time window."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

RS = "\x1e"  # record separator, one per commit
US = "\x1f"  # field separator inside the commit header

CONVENTIONAL = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(\([^)]*\))?!?: .+",
    re.IGNORECASE,
)

_VAGUE_WORDS = {
    "update",
    "updates",
    "updated",
    "fix",
    "fixes",
    "fixed",
    "changes",
    "change",
    "commit",
    "commit changes",
    "wip",
    "stuff",
    "misc",
    "cleanup",
    "final",
    "test",
    "tests",
    "asdf",
    ".",
    "..",
}


class GitError(RuntimeError):
    """Any failure while shelling out to git."""


class NotAGitRepository(GitError):
    """The requested path is not inside a git work tree."""


def _run(args: list[str], cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        message = proc.stderr.strip() or f"git {' '.join(args)} exited {proc.returncode}"
        raise GitError(message)
    return proc.stdout


def repo_root(path: Path) -> Path:
    """Return the work-tree root containing ``path``."""
    path = Path(path).expanduser()
    if not path.exists():
        raise NotAGitRepository(f"{path} does not exist")
    try:
        out = _run(["rev-parse", "--show-toplevel"], cwd=path)
    except GitError as exc:
        raise NotAGitRepository(f"{path} is not a git repository ({exc})") from exc
    return Path(out.strip())


def is_repo(path: Path) -> bool:
    try:
        repo_root(path)
    except NotAGitRepository:
        return False
    return True


def discover_repos(directory: Path, max_depth: int = 2) -> list[Path]:
    """Find git work trees at or below ``directory`` (breadth first)."""
    directory = Path(directory).expanduser()
    found: list[Path] = []
    if (directory / ".git").exists():
        return [directory]
    frontier = [(directory, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth > max_depth:
            continue
        try:
            children = sorted(p for p in current.iterdir() if p.is_dir())
        except OSError:
            continue
        for child in children:
            if child.name.startswith(".") and child.name != ".git":
                continue
            if (child / ".git").exists():
                found.append(child)
            elif depth < max_depth:
                frontier.append((child, depth + 1))
    return found


@dataclass(frozen=True)
class Commit:
    sha: str
    author: str
    email: str
    when: datetime
    subject: str
    parents: tuple[str, ...] = ()
    insertions: int = 0
    deletions: int = 0
    files: tuple[str, ...] = ()

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions

    @property
    def is_conventional(self) -> bool:
        return bool(CONVENTIONAL.match(self.subject))

    @property
    def is_vague(self) -> bool:
        subject = self.subject.strip().rstrip(".").lower()
        if subject in _VAGUE_WORDS:
            return True
        return len(subject) < 10 and not self.is_conventional


@dataclass
class Window:
    start: datetime
    end: datetime

    @property
    def days(self) -> int:
        return max(1, round((self.end - self.start).total_seconds() / 86400))

    def label(self) -> str:
        return f"{self.start:%Y-%m-%d} to {self.end:%Y-%m-%d}"


@dataclass
class Activity:
    """Aggregated commit activity inside one window."""

    window: Window
    commits: list[Commit] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.commits)

    @property
    def insertions(self) -> int:
        return sum(c.insertions for c in self.commits)

    @property
    def deletions(self) -> int:
        return sum(c.deletions for c in self.commits)

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions

    @property
    def files_touched(self) -> int:
        return len({path for c in self.commits for path in c.files})

    @property
    def authors(self) -> list[str]:
        seen: dict[str, int] = {}
        for commit in self.commits:
            seen[commit.author] = seen.get(commit.author, 0) + 1
        return [name for name, _ in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))]

    @property
    def active_days(self) -> int:
        return len({c.when.date() for c in self.commits})

    @property
    def merges(self) -> int:
        return sum(1 for c in self.commits if c.is_merge)

    @property
    def largest_commit(self) -> Commit | None:
        real = [c for c in self.commits if not c.is_merge]
        return max(real, key=lambda c: c.churn, default=None)

    @property
    def median_commit_churn(self) -> int:
        sizes = sorted(c.churn for c in self.commits if not c.is_merge)
        if not sizes:
            return 0
        middle = len(sizes) // 2
        if len(sizes) % 2:
            return sizes[middle]
        return (sizes[middle - 1] + sizes[middle]) // 2

    @property
    def conventional_ratio(self) -> float:
        real = [c for c in self.commits if not c.is_merge]
        if not real:
            return 0.0
        return sum(1 for c in real if c.is_conventional) / len(real)

    @property
    def vague_subjects(self) -> list[str]:
        seen: list[str] = []
        for commit in self.commits:
            if commit.is_merge or not commit.is_vague:
                continue
            if commit.subject not in seen:
                seen.append(commit.subject)
        return seen

    @property
    def busiest_day(self) -> tuple[str, int] | None:
        by_day: dict[str, int] = {}
        for commit in self.commits:
            key = commit.when.strftime("%Y-%m-%d")
            by_day[key] = by_day.get(key, 0) + 1
        if not by_day:
            return None
        day, hits = max(by_day.items(), key=lambda kv: (kv[1], kv[0]))
        return day, hits


@dataclass
class Snapshot:
    """Point-in-time facts about a repository, independent of the window."""

    root: Path
    name: str
    branch: str
    tracked_files: list[str] = field(default_factory=list)
    dirty_files: list[str] = field(default_factory=list)
    total_commits: int = 0
    first_commit: datetime | None = None
    last_commit: datetime | None = None
    has_remote: bool = False


def parse_log(output: str) -> list[Commit]:
    """Parse the output of the ``git log`` invocation used by :func:`collect`."""
    commits: list[Commit] = []
    for chunk in output.split(RS):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        lines = chunk.split("\n")
        header = lines[0]
        parts = header.split(US)
        if len(parts) < 6:
            continue
        sha, author, email, iso, parents, subject = parts[:6]
        try:
            when = datetime.fromisoformat(iso)
        except ValueError:
            continue
        insertions = deletions = 0
        files: list[str] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            bits = line.split("\t")
            if len(bits) < 3:
                continue
            added, removed, path = bits[0], bits[1], bits[-1]
            insertions += int(added) if added.isdigit() else 0
            deletions += int(removed) if removed.isdigit() else 0
            files.append(path)
        commits.append(
            Commit(
                sha=sha,
                author=author,
                email=email,
                when=when,
                subject=subject,
                parents=tuple(p for p in parents.split() if p),
                insertions=insertions,
                deletions=deletions,
                files=tuple(files),
            )
        )
    return commits


def collect(root: Path, window: Window) -> Activity:
    """Collect commits authored inside ``window``."""
    fmt = RS + US.join(["%H", "%an", "%ae", "%aI", "%P", "%s"])
    args = [
        "log",
        f"--since={window.start.isoformat()}",
        f"--until={window.end.isoformat()}",
        "--numstat",
        "--no-color",
        f"--pretty=format:{fmt}",
    ]
    try:
        output = _run(args, cwd=root)
    except GitError:
        # Repository without commits yet.
        return Activity(window=window)
    return Activity(window=window, commits=parse_log(output))


def snapshot(root: Path) -> Snapshot:
    """Gather repository-wide facts used by the health checks."""
    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root, check=False).strip()
    tracked = [line for line in _run(["ls-files"], cwd=root, check=False).splitlines() if line]
    dirty = [
        line[3:].strip()
        for line in _run(["status", "--porcelain"], cwd=root, check=False).splitlines()
        if line.strip()
    ]
    count_raw = _run(["rev-list", "--count", "HEAD"], cwd=root, check=False).strip()
    total = int(count_raw) if count_raw.isdigit() else 0
    first = _parse_boundary(root, ["log", "--reverse", "--date=iso-strict", "--format=%aI"], last=False)
    latest = _parse_boundary(root, ["log", "-1", "--date=iso-strict", "--format=%aI"], last=True)
    remotes = _run(["remote"], cwd=root, check=False).strip()
    return Snapshot(
        root=root,
        name=root.name,
        branch=branch or "(detached)",
        tracked_files=tracked,
        dirty_files=dirty,
        total_commits=total,
        first_commit=first,
        last_commit=latest,
        has_remote=bool(remotes),
    )


def _parse_boundary(root: Path, args: list[str], last: bool) -> datetime | None:
    out = _run(args, cwd=root, check=False).strip().splitlines()
    if not out:
        return None
    raw = out[-1] if last else out[0]
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
