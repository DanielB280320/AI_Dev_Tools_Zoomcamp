"""JSON-file persistence for projects and weekly entries.

The whole dataset is small (one row per project per week), so it lives in a
single JSON document that is rewritten atomically on every change.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import Entry, Project, ValidationError, normalize_slug, normalize_status

SCHEMA_VERSION = 1
DEFAULT_DIR = Path.home() / ".weekly-feedback"
DEFAULT_FILENAME = "data.json"
ENV_VAR = "WFB_DATA"


class StorageError(RuntimeError):
    """Raised when the data file cannot be read or written."""


def default_path() -> Path:
    """Data file location: ``$WFB_DATA`` if set, else ``~/.weekly-feedback/data.json``."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    return DEFAULT_DIR / DEFAULT_FILENAME


class Store:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_path()
        self._projects: dict[str, Project] = {}
        self._entries: dict[tuple[str, str], Entry] = {}
        self._loaded = False

    # ---------------------------------------------------------------- io ---
    def load(self) -> "Store":
        if self._loaded:
            return self
        self._loaded = True
        if not self.path.exists():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise StorageError(f"{self.path} is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise StorageError(f"cannot read {self.path}: {exc}") from exc

        version = raw.get("version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            raise StorageError(
                f"{self.path} was written by a newer version of this tool "
                f"(schema {version} > {SCHEMA_VERSION})"
            )

        for item in raw.get("projects", []):
            project = Project.from_dict(item)
            self._projects[project.slug] = project
        for item in raw.get("entries", []):
            entry = Entry.from_dict(item)
            self._entries[(entry.project, entry.week)] = entry
        return self

    def save(self) -> None:
        payload = {
            "version": SCHEMA_VERSION,
            "projects": [p.to_dict() for p in self.projects(include_archived=True)],
            "entries": [e.to_dict() for e in self.entries()],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a sibling temp file then rename, so an interrupted run
            # can never leave a half-written data file behind.
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                temp_name = handle.name
            os.replace(temp_name, self.path)
        except OSError as exc:
            raise StorageError(f"cannot write {self.path}: {exc}") from exc

    # ---------------------------------------------------------- projects ---
    def projects(self, include_archived: bool = False) -> list[Project]:
        values = sorted(self._projects.values(), key=lambda p: p.slug)
        if include_archived:
            return values
        return [p for p in values if not p.archived]

    def get_project(self, slug: str) -> Project | None:
        return self._projects.get(normalize_slug(slug))

    def require_project(self, slug: str) -> Project:
        project = self.get_project(slug)
        if project is None:
            known = ", ".join(p.slug for p in self.projects(include_archived=True))
            hint = f" Known projects: {known}." if known else ""
            raise ValidationError(f"no project {slug!r}.{hint}")
        return project

    def add_project(self, project: Project) -> Project:
        if project.slug in self._projects:
            raise ValidationError(f"project {project.slug!r} already exists")
        self._projects[project.slug] = project
        return project

    def set_archived(self, slug: str, archived: bool) -> Project:
        project = self.require_project(slug)
        project.archived = archived
        return project

    def remove_project(self, slug: str, drop_entries: bool = False) -> int:
        project = self.require_project(slug)
        removed = 0
        if drop_entries:
            for key in [k for k in self._entries if k[0] == project.slug]:
                del self._entries[key]
                removed += 1
        del self._projects[project.slug]
        return removed

    # ----------------------------------------------------------- entries ---
    def get_entry(self, project: str, week: str) -> Entry | None:
        return self._entries.get((normalize_slug(project), week))

    def put_entry(self, entry: Entry, mode: str = "error") -> Entry:
        """Store ``entry``.

        ``mode`` decides what happens when the project/week already has one:
        ``error`` refuses, ``replace`` overwrites, ``append`` merges.
        """
        key = (entry.project, entry.week)
        existing = self._entries.get(key)
        if existing is not None:
            if mode == "error":
                raise ValidationError(
                    f"{entry.project} already has feedback for {entry.week}; "
                    "pass --replace to overwrite or --append to add to it"
                )
            if mode == "append":
                entry = existing.merged_with(entry)
            elif mode == "replace":
                entry.created_at = existing.created_at
            else:  # pragma: no cover - guarded by the CLI
                raise ValueError(f"unknown put mode {mode!r}")
        self._entries[key] = entry
        return entry

    def delete_entry(self, project: str, week: str) -> bool:
        return self._entries.pop((normalize_slug(project), week), None) is not None

    def entries(
        self,
        project: str | None = None,
        week: str | None = None,
        status: str | None = None,
    ) -> list[Entry]:
        slug = normalize_slug(project) if project else None
        wanted_status = normalize_status(status) if status else None
        found = [
            entry
            for entry in self._entries.values()
            if (slug is None or entry.project == slug)
            and (week is None or entry.week == week)
            and (wanted_status is None or entry.status == wanted_status)
        ]
        # Newest week first, then alphabetical by project for a stable order.
        return sorted(found, key=lambda e: (e.week, e.project), reverse=False)

    def weeks(self) -> list[str]:
        return sorted({entry.week for entry in self._entries.values()})

    def history(self, project: str, week_keys: list[str]) -> list[Entry | None]:
        slug = normalize_slug(project)
        return [self._entries.get((slug, key)) for key in week_keys]
