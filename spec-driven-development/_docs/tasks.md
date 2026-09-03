# Backlog

Tasks derived from [`plan.md`](./plan.md). Section markers like (§2.4) point
back into that spec — read the named section and you have everything the task
needs; you should not need to read the other tasks.

They are ordered so each one starts from a working app, but they are written to
be picked up individually.

> Note: `main` already contains a working implementation of all of this. Treat
> this backlog as the build order it should have been done in — useful for
> rebuilding from scratch, splitting the work across people, or reviewing what
> landed against what was asked for.

---

## 1. Set up an empty project with a passing test
Goal: A runnable Django project whose test suite passes.
Description: Create the Django project and a single app backed by SQLite, so that the dev server starts and serves a placeholder page. Add one trivial test so `manage.py test` runs green against a real suite rather than an empty one. No models, views, or templates beyond the placeholder — this task exists so every later task starts from a working baseline. Note that this machine has no usable `pip` or `venv`; use `uv` to manage the environment.

## 2. Define the data model
Goal: Users, projects, and feedback entries exist as migrated tables.
Description: Add the three models in §7: `User` (a name and nothing else), `Project` (name, one manager, many members), and `FeedbackEntry` (project, author, a status of green/yellow/red, an optional note capped at 500 characters, and a timestamp). Entries are append-only — nothing in the app will ever edit or delete one — so default their ordering to newest-first and protect authors from deletion. Cover the model behaviour with tests; no UI in this task.

## 3. Add name-based identity
Goal: A visitor types a name and is recognised as that person for the session.
Description: Build a screen that accepts a name, creates that user if new, matches an existing one case-insensitively, and stores the id in the Django session (§2.1, §8). Add a "switch user" action that clears it, plus a guard that redirects anyone without a session to the identify screen. There are no passwords and no verification — this is a claim, not a credential, and that is deliberate for an internal, trust-based tool.

## 4. Create projects
Goal: A signed-in person can create a project and becomes its manager.
Description: Add a form taking a project name, which sets the creator as the project's manager and also adds them to the member list, since managers submit feedback like anyone else (§2.2, §2.3). Note that the spec is circular here — managers create projects, and a manager is someone who created one — and `User` carries no role field, so the working reading is that creating a project is what makes you its manager. Managership grants no authority on any other project.

## 5. Submit feedback
Goal: A project member can record a status and a note in under 30 seconds.
Description: Add a form with exactly two inputs — a status choice of green/yellow/red and an optional note — that appends a new row rather than updating any previous one (§2.4, §8). Resist adding fields: no separate blockers, wins, or mood, because submission speed is the point. Test that submitting twice leaves two rows, that the note is optional, and that a missing status is rejected.

## 6. Show the project timeline
Goal: A project page lists every entry, newest first.
Description: Render each entry as author, status icon, note, and a relative timestamp, in reverse-chronological order (§3.1). This is the detail view people read to find out what is actually going on, so it shows every member's entries without exception — there are no private or manager-only notes in the MVP (§2.6). Include an empty state for a project nobody has reported on yet.

## 7. Restrict projects to their members
Goal: People who aren't on a project can't see or post to it.
Description: Add a check to every project view and action so that only members can read or submit, and only the project's own manager can change its membership (§2.3, §2.6). Return 404 rather than 403 in both cases, so the tool never confirms to an outsider that a given project exists. Since anyone can claim any name at the identify screen, this is the only access boundary in the app and is worth testing directly.

## 8. Manage project membership
Goal: A manager can add and remove members by name.
Description: On the project page, show the member list and give the manager an add-by-name field and a remove action (§2.3). Removing someone unlinks their membership but leaves their past entries in place, because entries are immutable and the timeline should stay a truthful record of what was reported. The manager cannot be removed from their own project — the spec has no notion of transferring or vacating the role, so removing them would strand the project.

## 9. Build the dashboard
Goal: The home page lists the projects the signed-in person belongs to.
Description: Show one row per project with its name, the most recent status across all its members, and how long ago that entry landed (§3.3). Only the current person's projects appear — this is not a directory of everything that exists. Include an empty state for someone who isn't on any project yet, pointing them at creating one or asking a manager to add them.

## 10. Flag stale projects
Goal: Projects nobody has updated in 7+ days are visibly marked.
Description: On the dashboard, add a "stale" badge when a project's most recent entry is older than 7 days, counting a project with no entries at all as stale since it has never been reported on (§3.3). The threshold is fixed for every project — there is no per-project configuration in the MVP — so define it once in settings rather than inline. Compute it on page load; the MVP has no background job (§8).

## 11. Remind the person who is behind
Goal: Someone who hasn't posted in 7+ days sees a reminder, and nobody else does.
Description: On the dashboard, show a banner naming the projects where *this* person's own latest entry is older than 7 days or missing entirely (§4). It must not appear on anyone else's dashboard, must not notify the manager, and must not be broadcast to the project — the spec rejects both of those as recreating the deadline pressure the tool exists to remove. An in-app banner is the right delivery mechanism because it needs no email infrastructure.

## 12. Add the trend chart
Goal: A project page shows status over time at a glance.
Description: Plot entries on a three-point scale (red 1, yellow 2, green 3) with one line per person, so one person going red is not hidden behind three others staying green (§3.2). Avoid averaging the statuses into a single project line: that implies red, yellow, and green are evenly spaced, which the spec never claims. Hold each person's status until their next report rather than interpolating between points, since a status doesn't slide gradually.

## 13. Style the app
Goal: The tool reads as a finished internal tool rather than raw HTML.
Description: Add a single stylesheet covering the header, cards, tables, forms, and status badges, rendering the status picker as one-tap pills to keep submission fast. Make the layout hold up on a narrow screen. Skip the CSS framework — the app is four pages and a framework would outweigh it.

## 14. Write the README
Goal: A newcomer can install, run, and test the app from the README alone.
Description: Document what the tool is, then the commands to install dependencies, apply migrations, start the server, and run the tests. Link out to `plan.md` for the spec and `architecture.md` for the design decisions. State plainly that there is no authentication by design, so that nobody deploys it somewhere public by accident.
