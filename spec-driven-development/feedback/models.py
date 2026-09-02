"""Data model for the weekly project feedback tool (spec §7).

Three tables, and entries are append-only: nothing is ever edited or deleted,
which is what keeps the timeline and the trend chart honest.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class User(models.Model):
    """A person, identified by name alone (spec §2.1).

    This is *not* `django.contrib.auth.User` -- that app is not installed.
    There is no password, no email, and no verification: anyone with the URL
    can identify as a name. Roles are not stored here; being a manager is a
    property of a project (see `Project.manager`), because the same person is
    a manager on one project and a plain member on another (spec §2.2).
    """

    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Project(models.Model):
    """A project with one manager and a set of members (spec §2.3)."""

    name = models.CharField(max_length=120)
    manager = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="managed_projects"
    )
    members = models.ManyToManyField(User, related_name="projects")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def is_managed_by(self, user):
        return user is not None and self.manager_id == user.id

    def latest_entry(self):
        return self.entries.first()

    def is_stale(self):
        """True when nobody has submitted in STALE_AFTER_DAYS (spec §3.3).

        A project with no entries at all counts as stale -- it has never been
        reported on, which is the case most worth surfacing.
        """
        latest = self.latest_entry()
        if latest is None:
            return True
        return latest.created_at < timezone.now() - timedelta(
            days=settings.STALE_AFTER_DAYS
        )

    def latest_entry_per_member(self):
        """Most recent entry for each member, as {user_id: FeedbackEntry}.

        Members who have never submitted are absent from the mapping.
        """
        latest = {}
        for entry in self.entries.all().order_by("created_at"):
            latest[entry.author_id] = entry
        return latest


class FeedbackEntry(models.Model):
    """One person, one project, one point in time (spec §2.4).

    Immutable once written. A new submission is always a new row; it never
    overwrites the previous one.
    """

    class Status(models.TextChoices):
        GREEN = "green", "On track"
        YELLOW = "yellow", "At risk"
        RED = "red", "Blocked"

    # Mapped onto a 3-point scale for the trend chart (spec §3.2).
    SCORES = {Status.RED: 1, Status.YELLOW: 2, Status.GREEN: 3}
    ICONS = {Status.RED: "🔴", Status.YELLOW: "🟡", Status.GREEN: "🟢"}

    NOTE_MAX_LENGTH = 500

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="entries"
    )
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="entries")
    status = models.CharField(max_length=6, choices=Status.choices)
    note = models.TextField(max_length=NOTE_MAX_LENGTH, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Reverse-chronological by default: the timeline (§3.1) and
        # `latest_entry()` both want newest first.
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["project", "-created_at"])]

    def __str__(self):
        return f"{self.author} on {self.project}: {self.status}"

    @property
    def icon(self):
        return self.ICONS[self.Status(self.status)]

    @property
    def score(self):
        return self.SCORES[self.Status(self.status)]
