"""Load the optional project list from a TOML or JSON config file."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAMES = ("weekly-feedback.toml", ".weekly-feedback.toml", "projects.toml")

SAMPLE_CONFIG = """\
# weekly-feedback.toml — projects to include in the weekly report.

[defaults]
days = 7                 # length of the reporting window
format = "markdown"      # markdown | text | json
fail_under = 0           # exit non-zero when a project scores below this

# List repositories explicitly...
[[projects]]
name = "capstone"
path = "~/projects/capstone"

# [[projects]]
# name = "homework"
# path = "~/projects/homework"

# ...or point at a directory and pick up every repository inside it.
# [defaults]
# scan = ["~/projects"]
"""


class ConfigError(RuntimeError):
    """The config file exists but could not be used."""


@dataclass(frozen=True)
class ProjectSpec:
    name: str
    path: Path


@dataclass
class Config:
    projects: list[ProjectSpec] = field(default_factory=list)
    scan: list[Path] = field(default_factory=list)
    days: int = 7
    format: str = "markdown"
    fail_under: int = 0
    output: Path | None = None
    source: Path | None = None


def find_config(start: Path) -> Path | None:
    """Look for a config file in ``start`` and its parents."""
    start = Path(start).expanduser().resolve()
    for directory in [start, *start.parents]:
        for name in DEFAULT_CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def load(path: Path) -> Config:
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    raw = path.read_bytes()
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(raw.decode("utf-8"))
        else:
            data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"could not parse {path}: {exc}") from exc
    return from_mapping(data, source=path)


def from_mapping(data: dict, source: Path | None = None) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("config must be a table/object at the top level")
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("[defaults] must be a table")

    base = source.parent if source else Path.cwd()
    projects: list[ProjectSpec] = []
    for entry in data.get("projects", []) or []:
        if isinstance(entry, str):
            resolved = _resolve(entry, base)
            projects.append(ProjectSpec(name=resolved.name, path=resolved))
            continue
        if not isinstance(entry, dict) or "path" not in entry:
            raise ConfigError("every [[projects]] entry needs a path")
        resolved = _resolve(str(entry["path"]), base)
        projects.append(ProjectSpec(name=str(entry.get("name") or resolved.name), path=resolved))

    scan = [_resolve(str(p), base) for p in defaults.get("scan", []) or []]
    output = defaults.get("output")
    return Config(
        projects=projects,
        scan=scan,
        days=int(defaults.get("days", 7)),
        format=str(defaults.get("format", "markdown")),
        fail_under=int(defaults.get("fail_under", 0)),
        output=_resolve(str(output), base) if output else None,
        source=source,
    )


def _resolve(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    return path
