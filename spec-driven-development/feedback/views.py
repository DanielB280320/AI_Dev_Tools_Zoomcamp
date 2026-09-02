"""Views for the weekly project feedback tool.

Everything is computed on request -- staleness and reminders included. There
is no background job in the MVP (spec §8).
"""

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import AddMemberForm, FeedbackEntryForm, IdentifyForm, ProjectForm
from .identity import (
    clear_current_user,
    get_current_user,
    requires_identity,
    set_current_user,
)
from .models import FeedbackEntry, Project, User


def _stale_cutoff():
    return timezone.now() - timedelta(days=settings.STALE_AFTER_DAYS)


def identify(request):
    """Pick a name to act as (spec §2.1). This is the whole sign-in story."""
    if get_current_user(request) is not None:
        return redirect("dashboard")

    form = IdentifyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        set_current_user(request, form.get_or_create_user())
        return redirect("dashboard")

    return render(
        request,
        "feedback/identify.html",
        {"form": form, "known_users": User.objects.all()},
    )


@require_POST
def sign_out(request):
    clear_current_user(request)
    return redirect("identify")


@requires_identity
def dashboard(request, user):
    """Projects the current user belongs to, with status and staleness (§3.3)."""
    projects = (
        user.projects.select_related("manager")
        .prefetch_related(
            Prefetch(
                "entries",
                queryset=FeedbackEntry.objects.select_related("author"),
            )
        )
        .distinct()
    )

    cutoff = _stale_cutoff()
    rows = []
    reminders = []
    for project in projects:
        latest = project.latest_entry()
        rows.append(
            {
                "project": project,
                "latest": latest,
                "is_stale": latest is None or latest.created_at < cutoff,
            }
        )

        # Spec §4: the reminder goes only to the person who hasn't submitted,
        # never to the manager or the rest of the project.
        mine = project.latest_entry_per_member().get(user.id)
        if mine is None or mine.created_at < cutoff:
            reminders.append({"project": project, "last_submitted": mine})

    return render(
        request,
        "feedback/dashboard.html",
        {
            "rows": rows,
            "reminders": reminders,
            "stale_after_days": settings.STALE_AFTER_DAYS,
        },
    )


@requires_identity
def project_create(request, user):
    """Create a project; the creator becomes its manager (spec §2.2, §2.3).

    The spec says projects are created by managers and that managers are the
    people who created a project, and `User` carries no role field (§7). So
    the only consistent reading is: creating a project is what makes you its
    manager, and it grants no authority anywhere else.
    """
    form = ProjectForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.manager = user
        project.save()
        # The manager is a member too -- they submit feedback like anyone else.
        project.members.add(user)
        messages.success(request, f"Created {project.name}.")
        return redirect("project_detail", project_id=project.pk)

    return render(request, "feedback/project_form.html", {"form": form})


def _member_project_or_404(project_id, user):
    """Fetch a project the user belongs to.

    Non-members get a 404 rather than a 403 so the tool doesn't confirm which
    projects exist to people outside them.
    """
    project = get_object_or_404(Project.objects.select_related("manager"), pk=project_id)
    if not project.members.filter(pk=user.pk).exists():
        raise Http404("Not a member of this project")
    return project


def _trend_series(project):
    """Chart data: one light line per person (spec §3.2, §8).

    Per-person lines are the simpler of the two options the spec leaves open,
    and they avoid averaging green/yellow/red into a single number -- which
    would imply the three statuses are evenly spaced, a claim the spec never
    makes.
    """
    by_author = {}
    for entry in project.entries.select_related("author").order_by("created_at"):
        by_author.setdefault(entry.author.name, []).append(
            # Epoch milliseconds: keeps the chart on a plain linear axis,
            # so no Chart.js date adapter is needed.
            {"x": entry.created_at.timestamp() * 1000, "y": entry.score}
        )
    return [
        {"label": name, "points": points} for name, points in sorted(by_author.items())
    ]


@requires_identity
def project_detail(request, user, project_id):
    """Timeline (§3.1) + trend chart (§3.2) + the submission form."""
    project = _member_project_or_404(project_id, user)

    entries = project.entries.select_related("author")
    latest_per_member = project.latest_entry_per_member()
    cutoff = _stale_cutoff()

    member_rows = []
    for member in project.members.all():
        latest = latest_per_member.get(member.id)
        member_rows.append(
            {
                "user": member,
                "latest": latest,
                "is_manager": project.manager_id == member.id,
                "is_stale": latest is None or latest.created_at < cutoff,
            }
        )

    return render(
        request,
        "feedback/project_detail.html",
        {
            "project": project,
            "entries": entries,
            "member_rows": member_rows,
            "is_manager": project.is_managed_by(user),
            "form": FeedbackEntryForm(),
            "add_member_form": AddMemberForm(),
            "series": _trend_series(project),
            "stale_after_days": settings.STALE_AFTER_DAYS,
        },
    )


@require_POST
@requires_identity
def add_feedback(request, user, project_id):
    """Append an entry. Never updates an existing one (spec §2.4, §7)."""
    project = _member_project_or_404(project_id, user)

    form = FeedbackEntryForm(request.POST)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.project = project
        entry.author = user
        entry.save()
        messages.success(request, "Feedback recorded.")
    else:
        messages.error(request, "Pick a status before submitting.")

    return redirect("project_detail", project_id=project.pk)


def _managed_project_or_404(project_id, user):
    project = get_object_or_404(Project, pk=project_id)
    if not project.is_managed_by(user):
        raise Http404("Not the manager of this project")
    return project


@require_POST
@requires_identity
def add_member(request, user, project_id):
    """Only the managing user changes membership (spec §2.3)."""
    project = _managed_project_or_404(project_id, user)

    form = AddMemberForm(request.POST)
    if form.is_valid():
        member = form.get_or_create_user()
        project.members.add(member)
        messages.success(request, f"Added {member.name}.")
    else:
        messages.error(request, "Enter a name to add.")

    return redirect("project_detail", project_id=project.pk)


@require_POST
@requires_identity
def remove_member(request, user, project_id, member_id):
    project = _managed_project_or_404(project_id, user)

    if member_id == project.manager_id:
        # Removing the manager would leave the project unmanageable, and the
        # spec has no notion of transferring or vacating the role.
        messages.error(request, "The manager can't be removed from their own project.")
        return redirect("project_detail", project_id=project.pk)

    member = get_object_or_404(User, pk=member_id)
    project.members.remove(member)
    # Their past entries stay: entries are immutable and the timeline should
    # remain a truthful record of what was reported (spec §7).
    messages.success(request, f"Removed {member.name}.")
    return redirect("project_detail", project_id=project.pk)
