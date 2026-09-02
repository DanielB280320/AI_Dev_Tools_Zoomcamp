# Weekly Project Feedback Tool — MVP Specification

## 1. Purpose

A lightweight, always-current dashboard where team members and managers log
quick feedback on the projects they're part of. It replaces ad-hoc status
updates with a single shared source of truth: a color status plus a short
note, visible to everyone on the project, updated whenever something
changes — not on a forced weekly schedule.

The goal is low friction and high trust: fast to submit, transparent to
read, no gatekeeping on who sees what.

---

## 2. Core Concepts

### 2.1 Users
- A user has a **name** only. No password, no email verification, no SSO.
- Anyone with the app URL can identify as a name and act as that user.
- Rationale: this is an internal, trust-based tool. Real auth adds setup
  cost with no security benefit for this use case. Revisit if the tool
  ever needs to leave a trusted internal group.

### 2.2 Roles
- **Manager**: can create projects, add/remove project members, and submit
  feedback like any other member.
- **Team member**: can submit feedback on projects they belong to and view
  everything on those projects. Cannot create projects or manage
  membership.
- A user can be a manager on one project and a plain member on another.

### 2.3 Projects
- Created only by managers.
- Each project has: a name, a manager (creator), and a list of members
  (team members + manager).
- Only the managing user can add or remove members from a project.
- Rationale: keeps project structure controlled and prevents accidental
  sprawl (random people creating projects, adding themselves to things
  they shouldn't see).

### 2.4 Feedback Entries
- One entry = one person, one project, one point in time.
- Fields:
  - **Status**: one of 🟢 (on track) / 🟡 (at risk) / 🔴 (blocked/off track)
  - **Note**: free text, optional length limit (e.g. 500 chars) to keep
    entries skimmable
  - **Author** (auto-filled from logged-in name)
  - **Timestamp** (auto-filled)
- No other structured fields (no separate "blockers", "wins", "mood"
  fields) — status + note is the entire form. Keeps submission under 30
  seconds.
- A user can submit a new entry for a project at any time — there's no
  "one per week" cap. Each submission is a new entry; it doesn't overwrite
  the previous one.

### 2.5 Submission Cadence
- **Rolling, not scheduled.** No fixed submission window, no weekly
  deadline, no batch processing.
- The dashboard always reflects the latest entry per person per project.
- Rationale: removes deadline pressure and the "everyone submits Friday at
  4:59pm" scramble. People update when something actually changes.

### 2.6 Visibility
- **Fully open.** Every member of a project can see every entry on that
  project — manager notes, team member notes, all of it.
- No private or manager-only entries in MVP.
- Rationale: transparency was chosen deliberately to build trust; adding
  visibility tiers later is possible but not needed for MVP.

---

## 3. Views

### 3.1 Project Timeline
- Reverse-chronological list of all feedback entries for a project.
- Each row: author, status icon, note, timestamp.
- This is the "detail" view — read it to understand what's actually
  happening.

### 3.2 Project Trend Chart
- Plots status (🟢🟡🔴, e.g. mapped to a 3-point scale) over time for the
  project.
- One line/series representing overall project status trend, built from
  the sequence of entries.
- Purpose: see at a glance whether a project is improving, stable, or
  declining without reading every entry.
- If multiple people submit in the same period, the trend chart can show
  the most recent status per person, or an aggregate (e.g. most common
  status) — implementation detail to decide during build, not a scope
  blocker.

### 3.3 Dashboard (Home)
- List of all projects the logged-in user belongs to.
- Each project row shows: current/latest overall status, last updated
  timestamp, and a "stale" indicator if no one has submitted in 7+ days
  (see §4).

---

## 4. Freshness / Reminders

- If a project member hasn't submitted a new entry in **7 days**, they get
  a reminder.
- The threshold is **fixed at 7 days for all projects** — no per-project
  configuration in MVP.
  - *Why:* per-project settings mean another screen for managers to
    maintain before there's even data to look at. 7 days matches a
    "weekly" tool's natural cadence.
- Reminders are sent **only to the specific person who hasn't submitted**,
  not broadcast to the whole project.
  - *Why:* the whole point of a rolling, deadline-free cycle is reduced
    pressure. Notifying the whole project when two people are behind
    creates noise and mild public pressure, which undercuts that design
    choice. Alternative considered: notify the manager to chase people —
    rejected because it recreates a "manager as nag" dynamic that
    conflicts with the open, trust-based tone of the tool.
- Reminder delivery mechanism (email, in-app banner, etc.) is an
  implementation detail — not fixed in this spec. In-app banner on login
  is the simplest MVP option if no email system is set up.

---

## 5. Platform

- **Standalone web application** (not a Slack/Teams bot).
- Rationale: no dependency on a chat platform, one central place people
  go to check on projects, easier to build a real dashboard/trend view in
  a web app than in a chat surface.

---

## 6. Explicitly Out of Scope for MVP

These were considered and deliberately deferred, not forgotten:

- Real authentication (email/password or SSO)
- Per-project reminder thresholds
- Reminders broadcast to whole project or routed through managers
- Reporting/export (CSV, digest emails, PDF reports)
- Private/manager-only feedback visibility tiers
- Custom per-project form fields
- Fixed submission windows or batch summary emails
- Mobile app / chat bot interface

If any of these become necessary post-MVP, they can be layered on without
restructuring the core data model (users, projects, entries).

---

## 7. Data Model Sketch

```
User
  - id
  - name

Project
  - id
  - name
  - manager_id (User)
  - members [User]

FeedbackEntry
  - id
  - project_id (Project)
  - author_id (User)
  - status (enum: green | yellow | red)
  - note (text, optional max length)
  - created_at (timestamp)
```

No entry is ever edited or deleted in MVP — each submission is an
immutable new row. This keeps the timeline and trend chart accurate and
avoids building edit/delete permission logic.

---

## 8. Build Notes for the Agent

- Prioritize submission speed: the "add feedback" form should be status +
  note, nothing else, and completable in under 30 seconds.
- The dashboard's "staleness" flag (§4) can be computed client-side or
  server-side from `created_at` on the latest entry per project member —
  no need for a background job in MVP, a check-on-load is sufficient.
- Since there's no real auth, treat "logged in as X" as a lightweight
  session (e.g. a name picker/entry on load, stored in local
  session/cookie) rather than a full account system.
- Trend chart aggregation logic (per-person vs. project-level aggregate)
  is left as an implementation choice — pick the simpler one to ship
  first (most recent status per person, plotted as separate light lines
  or averaged into one line) and iterate.
