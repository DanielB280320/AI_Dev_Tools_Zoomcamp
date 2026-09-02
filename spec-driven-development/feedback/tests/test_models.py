from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from feedback.models import FeedbackEntry, Project, User


def make_entry(project, author, status=FeedbackEntry.Status.GREEN, days_ago=0, note=""):
    entry = FeedbackEntry.objects.create(
        project=project, author=author, status=status, note=note
    )
    if days_ago:
        # created_at is auto_now_add, so backdating needs a direct update.
        stamp = timezone.now() - timedelta(days=days_ago)
        FeedbackEntry.objects.filter(pk=entry.pk).update(created_at=stamp)
        entry.refresh_from_db()
    return entry


class ProjectStalenessTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create(name="Ada")
        self.project = Project.objects.create(name="Apollo", manager=self.manager)
        self.project.members.add(self.manager)

    def test_project_with_no_entries_is_stale(self):
        self.assertTrue(self.project.is_stale())

    def test_recent_entry_is_not_stale(self):
        make_entry(self.project, self.manager, days_ago=1)
        self.assertFalse(self.project.is_stale())

    def test_entry_older_than_threshold_is_stale(self):
        make_entry(self.project, self.manager, days_ago=8)
        self.assertTrue(self.project.is_stale())

    def test_latest_entry_per_member_keeps_only_the_newest(self):
        other = User.objects.create(name="Grace")
        self.project.members.add(other)
        make_entry(self.project, self.manager, FeedbackEntry.Status.RED, days_ago=3)
        newest = make_entry(self.project, self.manager, FeedbackEntry.Status.GREEN)
        theirs = make_entry(self.project, other, FeedbackEntry.Status.YELLOW, days_ago=1)

        latest = self.project.latest_entry_per_member()
        self.assertEqual(latest[self.manager.id], newest)
        self.assertEqual(latest[other.id], theirs)


class FeedbackEntryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(name="Ada")
        self.project = Project.objects.create(name="Apollo", manager=self.user)
        self.project.members.add(self.user)

    def test_entries_are_ordered_newest_first(self):
        old = make_entry(self.project, self.user, days_ago=2)
        new = make_entry(self.project, self.user)
        self.assertEqual(list(self.project.entries.all()), [new, old])

    def test_status_maps_to_icon_and_score(self):
        entry = make_entry(self.project, self.user, FeedbackEntry.Status.YELLOW)
        self.assertEqual(entry.icon, "🟡")
        self.assertEqual(entry.score, 2)
