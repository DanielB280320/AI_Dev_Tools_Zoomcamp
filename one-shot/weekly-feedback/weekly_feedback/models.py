"""Data model for projects and weekly feedback entries."""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field, asdict

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

#: Canonical status values, best-to-worst. ``green`` = on track, ``amber`` =
#: at risk, ``red`` = blocked or off track.
STATUSES = ("green", "amber", "red")

_STATUS_ALIASES = {
    "g": "green", "green": "green", "ok": "green", "on-track": "green", "ontrack": "green",
    "a": "amber", "amber": "amber", "yellow": "amber", "y": "amber", "at-risk": "amber",
    "r": "red", "red": "red", "blocked": "red", "off-track": "red",
}

STATUS_ICONS = {"green": "🟢", "amber": "🟡", "red": "🔴"}
STATUS_MARKS = {"green": "+", "amber": "~", "red": "!"}


class ValidationError(ValueError):
    """Raised when user input does not fit the model."""


def normalize_slug(value: str) -> str:
    slug = value.strip().lower().replace(" ", "-")
    if not SLUG_RE.match(slug):
        raise ValidationError(
            f"{value!r} is not a valid project id; use lowercase letters, digits, "
            "'.', '_' or '-' (max 64 chars)"
        )
    return slug


def normalize_status(value: str) -> str:
    status = _STATUS_ALIASES.get(value.strip().lower())
    if status is None:
        raise ValidationError(
            f"unknown status {value!r}; expected one of {', '.join(STATUSES)}"
        )
    return status


def normalize_rating(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        rating = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"rating must be a whole number 1-5, got {value!r}") from exc
    if not 1 <= rating <= 5:
        raise ValidationError(f"rating must be between 1 and 5, got {rating}")
    return rating


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _clean_lines(values: list[str] | None) -> list[str]:
    """Drop blanks and strip whitespace from a repeatable ``--flag`` list."""
    return [line.strip() for line in (values or []) if line and line.strip()]


@dataclass
class Project:
    slug: str
    name: str
    owner: str = ""
    archived: bool = False
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def create(cls, slug: str, name: str | None = None, owner: str = "") -> "Project":
        slug = normalize_slug(slug)
        return cls(slug=slug, name=(name or slug).strip(), owner=owner.strip())

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        return cls(
            slug=data["slug"],
            name=data.get("name") or data["slug"],
            owner=data.get("owner", ""),
            archived=bool(data.get("archived", False)),
            created_at=data.get("created_at") or now_iso(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def label(self) -> str:
        return self.name if self.name != self.slug else self.slug


@dataclass
class Entry:
    """One project's feedback for one ISO week."""

    project: str
    week: str
    status: str = "green"
    author: str = ""
    rating: int | None = None
    highlights: list[str] = field(default_factory=list)
    lowlights: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @classmethod
    def create(
        cls,
        project: str,
        week: str,
        status: str = "green",
        author: str = "",
        rating: object = None,
        highlights: list[str] | None = None,
        lowlights: list[str] | None = None,
        blockers: list[str] | None = None,
        next_steps: list[str] | None = None,
        notes: str = "",
    ) -> "Entry":
        return cls(
            project=normalize_slug(project),
            week=week,
            status=normalize_status(status),
            author=author.strip(),
            rating=normalize_rating(rating),
            highlights=_clean_lines(highlights),
            lowlights=_clean_lines(lowlights),
            blockers=_clean_lines(blockers),
            next_steps=_clean_lines(next_steps),
            notes=notes.strip(),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        return cls(
            project=data["project"],
            week=data["week"],
            status=normalize_status(data.get("status", "green")),
            author=data.get("author", ""),
            rating=normalize_rating(data.get("rating")),
            highlights=list(data.get("highlights", [])),
            lowlights=list(data.get("lowlights", [])),
            blockers=list(data.get("blockers", [])),
            next_steps=list(data.get("next_steps", [])),
            notes=data.get("notes", ""),
            created_at=data.get("created_at") or now_iso(),
            updated_at=data.get("updated_at") or now_iso(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def merged_with(self, other: "Entry") -> "Entry":
        """Return ``self`` updated by the non-empty fields of ``other``.

        Used by ``submit --append`` so a second submission in the same week adds
        to the existing entry instead of replacing it.
        """
        return Entry(
            project=self.project,
            week=self.week,
            status=other.status,
            author=other.author or self.author,
            rating=other.rating if other.rating is not None else self.rating,
            highlights=self.highlights + other.highlights,
            lowlights=self.lowlights + other.lowlights,
            blockers=self.blockers + other.blockers,
            next_steps=self.next_steps + other.next_steps,
            notes="\n".join(part for part in (self.notes, other.notes) if part),
            created_at=self.created_at,
            updated_at=now_iso(),
        )

    @property
    def is_empty(self) -> bool:
        return not any(
            (self.highlights, self.lowlights, self.blockers, self.next_steps, self.notes)
        )
