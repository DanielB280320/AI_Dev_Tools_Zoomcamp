from django.test import TestCase
from django.urls import reverse

from feedback.identity import SESSION_KEY
from feedback.models import FeedbackEntry, Project, User

from .test_models import make_entry


class IdentifyTests(TestCase):
    def test_new_name_creates_a_user_and_starts_a_session(self):
        response = self.client.post(reverse("identify"), {"name": "Ada"})
        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(name="Ada")
        self.assertEqual(self.client.session[SESSION_KEY], user.pk)

    def test_existing_name_is_matched_case_insensitively(self):
        ada = User.objects.create(name="Ada")
        self.client.post(reverse("identify"), {"name": "  ada  "})
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(self.client.session[SESSION_KEY], ada.pk)

    def test_dashboard_redirects_when_nobody_has_identified(self):
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("identify"))

    def test_sign_out_clears_the_session(self):
        self.client.post(reverse("identify"), {"name": "Ada"})
        self.client.post(reverse("sign_out"))
        self.assertNotIn(SESSION_KEY, self.client.session)


class IdentifiedTestCase(TestCase):
    """Base class that signs a name in and can switch between people."""

    def identify_as(self, name):
        user, _ = User.objects.get_or_create(name=name)
        session = self.client.session
        session[SESSION_KEY] = user.pk
        session.save()
        return user


class ProjectCreationTests(IdentifiedTestCase):
    def test_creator_becomes_manager_and_member(self):
        ada = self.identify_as("Ada")
        self.client.post(reverse("project_create"), {"name": "Apollo"})

        project = Project.objects.get(name="Apollo")
        self.assertEqual(project.manager, ada)
        self.assertIn(ada, project.members.all())


class ProjectAccessTests(IdentifiedTestCase):
    def setUp(self):
        self.manager = User.objects.create(name="Ada")
        self.project = Project.objects.create(name="Apollo", manager=self.manager)
        self.project.members.add(self.manager)
        self.url = reverse("project_detail", args=[self.project.pk])

    def test_member_can_view_the_project(self):
        self.identify_as("Ada")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_non_member_gets_404_not_403(self):
        # A 403 would confirm the project exists to someone outside it.
        self.identify_as("Outsider")
        self.assertEqual(self.client.get(self.url).status_code, 404)


class FeedbackSubmissionTests(IdentifiedTestCase):
    def setUp(self):
        self.ada = self.identify_as("Ada")
        self.project = Project.objects.create(name="Apollo", manager=self.ada)
        self.project.members.add(self.ada)
        self.url = reverse("add_feedback", args=[self.project.pk])

    def test_submission_appends_rather_than_overwriting(self):
        self.client.post(self.url, {"status": "green", "note": "first"})
        self.client.post(self.url, {"status": "red", "note": "second"})

        entries = list(self.project.entries.all())
        self.assertEqual(len(entries), 2)
        self.assertEqual([e.note for e in entries], ["second", "first"])

    def test_note_is_optional(self):
        self.client.post(self.url, {"status": "green", "note": ""})
        self.assertEqual(self.project.entries.count(), 1)

    def test_status_is_required(self):
        self.client.post(self.url, {"status": "", "note": "no status"})
        self.assertEqual(self.project.entries.count(), 0)

    def test_note_longer_than_the_limit_is_rejected(self):
        long_note = "x" * (FeedbackEntry.NOTE_MAX_LENGTH + 1)
        self.client.post(self.url, {"status": "green", "note": long_note})
        self.assertEqual(self.project.entries.count(), 0)

    def test_non_member_cannot_submit(self):
        self.identify_as("Outsider")
        response = self.client.post(self.url, {"status": "green", "note": "hi"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.project.entries.count(), 0)


class MembershipTests(IdentifiedTestCase):
    def setUp(self):
        self.ada = User.objects.create(name="Ada")
        self.grace = User.objects.create(name="Grace")
        self.project = Project.objects.create(name="Apollo", manager=self.ada)
        self.project.members.add(self.ada, self.grace)

    def test_manager_can_add_a_member_by_name(self):
        self.identify_as("Ada")
        self.client.post(
            reverse("add_member", args=[self.project.pk]), {"name": "Alan"}
        )
        self.assertTrue(self.project.members.filter(name="Alan").exists())

    def test_manager_can_remove_a_member(self):
        self.identify_as("Ada")
        self.client.post(
            reverse("remove_member", args=[self.project.pk, self.grace.pk])
        )
        self.assertNotIn(self.grace, self.project.members.all())

    def test_removing_a_member_keeps_their_entries(self):
        self.identify_as("Ada")
        make_entry(self.project, self.grace)
        self.client.post(
            reverse("remove_member", args=[self.project.pk, self.grace.pk])
        )
        self.assertEqual(self.project.entries.filter(author=self.grace).count(), 1)

    def test_plain_member_cannot_add_members(self):
        self.identify_as("Grace")
        response = self.client.post(
            reverse("add_member", args=[self.project.pk]), {"name": "Alan"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.project.members.filter(name="Alan").exists())

    def test_plain_member_cannot_remove_members(self):
        self.identify_as("Grace")
        response = self.client.post(
            reverse("remove_member", args=[self.project.pk, self.ada.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn(self.ada, self.project.members.all())

    def test_manager_cannot_be_removed_from_their_own_project(self):
        self.identify_as("Ada")
        self.client.post(reverse("remove_member", args=[self.project.pk, self.ada.pk]))
        self.assertIn(self.ada, self.project.members.all())


class DashboardTests(IdentifiedTestCase):
    def setUp(self):
        self.ada = self.identify_as("Ada")
        self.grace = User.objects.create(name="Grace")
        self.project = Project.objects.create(name="Apollo", manager=self.ada)
        self.project.members.add(self.ada, self.grace)

    def test_only_shows_projects_the_user_belongs_to(self):
        Project.objects.create(name="Gemini", manager=self.grace).members.add(self.grace)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Apollo")
        self.assertNotContains(response, "Gemini")

    def test_reminder_appears_when_the_user_is_behind(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(len(response.context["reminders"]), 1)

    def test_reminder_clears_after_the_user_submits(self):
        make_entry(self.project, self.ada)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["reminders"], [])

    def test_someone_elses_lateness_does_not_remind_you(self):
        # Spec §4: reminders go only to the person who is behind.
        make_entry(self.project, self.ada)
        make_entry(self.project, self.grace, days_ago=30)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["reminders"], [])


class TrendChartTests(IdentifiedTestCase):
    def test_one_series_per_author_in_chronological_order(self):
        ada = self.identify_as("Ada")
        grace = User.objects.create(name="Grace")
        project = Project.objects.create(name="Apollo", manager=ada)
        project.members.add(ada, grace)

        make_entry(project, ada, FeedbackEntry.Status.RED, days_ago=3)
        make_entry(project, ada, FeedbackEntry.Status.GREEN)
        make_entry(project, grace, FeedbackEntry.Status.YELLOW, days_ago=1)

        response = self.client.get(reverse("project_detail", args=[project.pk]))
        series = response.context["series"]

        self.assertEqual([s["label"] for s in series], ["Ada", "Grace"])
        self.assertEqual([p["y"] for p in series[0]["points"]], [1, 3])
        self.assertEqual([p["y"] for p in series[1]["points"]], [2])
