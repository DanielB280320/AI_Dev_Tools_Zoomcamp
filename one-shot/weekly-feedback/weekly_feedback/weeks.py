"""ISO week helpers.

A "week key" in this tool is always an ISO-8601 week string like ``2026-W36``.
Weeks are the unit everything else hangs off, so parsing lives in one place.
"""

from __future__ import annotations

import datetime as _dt
import re

WEEK_RE = re.compile(r"^(\d{4})-?W(\d{1,2})$", re.IGNORECASE)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class WeekError(ValueError):
    """Raised when a week expression cannot be understood."""


def week_key(date: _dt.date) -> str:
    """Return the ISO week key (``YYYY-Www``) containing ``date``."""
    year, week, _ = date.isocalendar()
    return f"{year}-W{week:02d}"


def current_week(today: _dt.date | None = None) -> str:
    return week_key(today or _dt.date.today())


def week_start(key: str) -> _dt.date:
    """Monday of the given week key."""
    year, week = _split(key)
    try:
        return _dt.date.fromisocalendar(year, week, 1)
    except ValueError as exc:  # e.g. week 53 of a 52-week year
        raise WeekError(f"{key} is not a real ISO week") from exc


def week_end(key: str) -> _dt.date:
    return week_start(key) + _dt.timedelta(days=6)


def shift(key: str, weeks: int) -> str:
    """Return the week key ``weeks`` away from ``key`` (may be negative)."""
    return week_key(week_start(key) + _dt.timedelta(weeks=weeks))


def week_range_label(key: str) -> str:
    start, end = week_start(key), week_end(key)
    if start.year == end.year:
        return f"{start:%b %d} - {end:%b %d, %Y}"
    return f"{start:%b %d, %Y} - {end:%b %d, %Y}"


def recent_weeks(key: str, count: int) -> list[str]:
    """``count`` week keys ending at (and including) ``key``, oldest first."""
    if count < 1:
        raise WeekError("count must be at least 1")
    return [shift(key, offset) for offset in range(-(count - 1), 1)]


def parse(expr: str | None, today: _dt.date | None = None) -> str:
    """Turn a user-supplied week expression into a canonical week key.

    Accepts ``2026-W36``/``2026W36``, ``current``/``this``, ``last``/``previous``,
    ``next``, a relative offset such as ``-3``, or any ``YYYY-MM-DD`` date.
    """
    today = today or _dt.date.today()
    if expr is None:
        return week_key(today)

    text = expr.strip().lower()
    if not text or text in {"current", "this", "now", "this-week"}:
        return week_key(today)
    if text in {"last", "previous", "prev"}:
        return shift(week_key(today), -1)
    if text == "next":
        return shift(week_key(today), 1)

    match = WEEK_RE.match(text)
    if match:
        key = f"{int(match.group(1))}-W{int(match.group(2)):02d}"
        week_start(key)  # validates the week number against the year
        return key

    match = DATE_RE.match(text)
    if match:
        try:
            date = _dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError as exc:
            raise WeekError(f"{expr!r} is not a real date") from exc
        return week_key(date)

    if re.fullmatch(r"[+-]\d+", text):
        return shift(week_key(today), int(text))

    raise WeekError(
        f"cannot read week {expr!r}; use 2026-W36, a YYYY-MM-DD date, "
        "current/last/next, or an offset like -2"
    )


def _split(key: str) -> tuple[int, int]:
    match = WEEK_RE.match(key.strip())
    if not match:
        raise WeekError(f"{key!r} is not a week key like 2026-W36")
    year, week = int(match.group(1)), int(match.group(2))
    if not 1 <= week <= 53:
        raise WeekError(f"{key!r} has no such ISO week number")
    return year, week
