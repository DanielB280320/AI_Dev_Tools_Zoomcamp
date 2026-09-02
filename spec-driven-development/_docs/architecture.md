# Weekly Project Feedback Tool — Architecture

Companion to [`plan.md`](./plan.md). The plan says *what* the tool does; this
says *how* it is built and *why* each choice was made. Section references like
(§2.4) point back into the plan.

---

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.13 | Matches the rest of this repo |
| Framework | Django 6.1 | ORM, migrations, templates, CSRF, forms — batteries for a CRUD app |
| Database | SQLite | Three tables, append-only, single writer. Nothing here needs Postgres |
| Templates | Django templates, server-rendered | No build step, no client state, no API layer |
| Chart | Chart.js 4.4 from CDN | The one genuinely UI-hard piece (§3.2) |
| Styling | One hand-written CSS file | ~180 lines. A framework would be larger than the app |
| Packaging | `uv` | The environment had no `pip` or working `venv` |

Django was chosen over the alternatives on the strength of its ORM, migrations,
and form handling for what is fundamentally a small CRUD app, and because the
deferred items in §6 (real auth, exports, visibility tiers) are all things
Django has a well-worn path for later.

### 1.1 The one significant deviation: no `django.contrib.auth`

**`django.contrib.auth` is not installed, and neither is the Django admin.**

The spec is emphatic that a user is a name and nothing else — no password, no
email, no SSO (§2.1) — and that identity should be "a lightweight session
rather than a full account system" (§8). Django's auth app assumes the
opposite at every turn: password hashing, a login backend, permissions,
`request.user`.

Keeping it would have meant creating auth users with unusable passwords and
then routing around the parts that expect real credentials. Dropping it means:

- `feedback.User` is unambiguous — there is no second `User` model in the
  project to confuse it with.
- There are no passwords anywhere in the codebase, which is exactly what §2.1
  describes.
- **Cost:** the free admin UI goes with it, so the member-management screen is
  hand-built.

That cost is smaller than it first appears. §2.3 requires that *only the
managing user* can change a project's membership — a per-object permission the
Django admin does not express well. That screen was going to be hand-built
either way.

Everything else Django provides — ORM, migrations, templates, forms, CSRF,
sessions, `staticfiles` — is used normally.

---

## 2. Module map

```
config/                    Django project
  settings.py              Short INSTALLED_APPS; STALE_AFTER_DAYS lives here
  urls.py                  Delegates everything to feedback.urls

feedback/                  The single app
  models.py                User, Project, FeedbackEntry (§7)
  identity.py              Session-as-a-name + @requires_identity decorator
  context_processors.py    Puts current_user in every template
  forms.py                 Identify, Project, FeedbackEntry, AddMember
  views.py                 8 views; all logic computed per-request
  urls.py                  URL table
  templates/feedback/      base + 4 pages
  static/feedback/         app.css, trend.js
  tests/                   29 tests across models and views
```

Deliberately absent: no `services/`, no `repositories/`, no serializers, no
API. At this size those layers add indirection without removing any.

---

## 3. Data model

```
User                Project                      FeedbackEntry
  id                  id                           id
  name (unique)       name                         project_id  ──> Project
                      manager_id  ──> User         author_id   ──> User
                      members     <──> User (M2M)  status      green|yellow|red
                      created_at                   note        text, max 500
                                                   created_at
```

Three properties do most of the work:

**Entries are append-only.** No view updates or deletes a `FeedbackEntry`.
Every submission is a new row (§2.4, §7). This is what keeps the timeline and
the trend chart truthful, and it means there is no edit/delete permission logic
to write.

**Roles are per-project, not per-user.** `User` has no role column. Being a
manager is `Project.manager_id == user.id`, which is what makes "manager on one
project, plain member on another" (§2.2) fall out for free.

**Authors are `PROTECT`ed.** A `User` with entries cannot be deleted out from
under the timeline. Removing someone from a project unlinks the membership but
leaves their entries in place — the record of what was reported stays accurate.

Default ordering on `FeedbackEntry` is `-created_at`, which the timeline (§3.1)
and `latest_entry()` both want, plus an index on `(project, -created_at)`.

---

## 4. Identity and access control

### 4.1 Identity

`feedback/identity.py`. The chosen `User.id` is stored in the Django session
cookie. `@requires_identity` wraps every view, redirecting to `/identify/` when
the session is empty and otherwise passing the `User` in as the second
argument.

This is a **claim, not a credential**. Anyone with the URL can identify as any
name. That is the spec's deliberate choice (§2.1) for an internal, trust-based
tool, and it is the single thing to revisit before this leaves a trusted group.

Names are matched case-insensitively so "ada" and "Ada" don't become two
people.

### 4.2 Access control

Two checks, both in `views.py`:

| Helper | Rule | Spec |
|---|---|---|
| `_member_project_or_404` | Must be a project member to read or submit | §2.6 |
| `_managed_project_or_404` | Must be the manager to change membership | §2.3 |

Both raise **404, not 403**, for the failing case. A 403 would confirm to an
outsider that a given project exists. Since anyone can claim any name, leaking
project names to a wrong guess is worth avoiding.

---

## 5. Request flows

**Submitting feedback** — the path optimised for (§8: under 30 seconds):

```
POST /projects/<id>/feedback/
  → @requires_identity resolves the session name
  → _member_project_or_404 confirms membership
  → FeedbackEntryForm validates status + note (nothing else)
  → INSERT a new row (never an UPDATE)
  → redirect back to the project page
```

The form is a radio group and a textarea. There are no other fields, by design.

**Loading the dashboard:**

```
GET /
  → projects the user belongs to, entries prefetched
  → per project: latest entry → status + "stale" badge (§3.3)
  → per project: this user's own latest entry → reminder or not (§4)
```

---

## 6. Freshness, computed not scheduled

There is **no background job, no cron, no queue** (§8). Both freshness signals
are derived on page load from `created_at`:

- **Stale badge** (§3.3) — *nobody* has submitted on this project in 7+ days.
  A project with zero entries counts as stale; it has never been reported on,
  which is the case most worth surfacing.
- **Reminder banner** (§4) — *you* haven't submitted on this project in 7+
  days. It is rendered only on your own dashboard.

The reminder is deliberately not an email and not a broadcast. §4 rejects both
whole-project notification and manager-chasing as undercutting the tool's
low-pressure, trust-based design; an in-app banner is the delivery mechanism
that needs no infrastructure and reaches exactly one person.

`STALE_AFTER_DAYS = 7` is a single setting in `config/settings.py` — fixed for
all projects, per §4.

---

## 7. The trend chart

§3.2 explicitly leaves the aggregation choice open. **One line per person** was
chosen, plotted on a 3-point scale (🔴 1 / 🟡 2 / 🟢 3).

The alternative — averaging everyone's status into a single project line —
was rejected because averaging red/yellow/green implies the three statuses are
*evenly spaced*, a claim the spec never makes. The gap between "on track" and
"at risk" is not obviously the same size as the gap between "at risk" and
"blocked", and a single averaged line quietly hides one person going red behind
three people staying green — the exact signal the chart exists to surface.

Two implementation notes:

- The line is **stepped**, not smoothed. A status holds until the next report;
  interpolating between them would draw a gradual slide that never happened.
- X values are **epoch milliseconds on a linear axis**, so Chart.js needs no
  date-adapter dependency. Data reaches the page through Django's
  `json_script` filter, which escapes it safely.

---

## 8. Where the spec was ambiguous

Three places needed a judgement call. Each is commented at the relevant code.

**"Projects are created only by managers" (§2.3) is circular** — a manager is
defined as someone who created a project, and `User` has no role field (§7).
Resolution: *any user may create a project and thereby becomes its manager*.
Managership grants no authority anywhere else. This is the only reading
consistent with a role-free `User`.

**Removing a member and their history.** The spec doesn't say. Resolution:
membership is removed, entries stay. Entries are immutable (§7), and deleting
history would falsify a timeline that other people already read.

**Removing the manager.** The spec has no notion of transferring or vacating
the role, so a manager cannot be removed from their own project — it would
leave the project permanently unmanageable.

---

## 9. Testing

29 tests, `uv run python manage.py test`.

- `tests/test_models.py` — staleness thresholds, latest-entry-per-member,
  ordering, status→icon/score mapping.
- `tests/test_views.py` — identity and sessions, access control (member and
  manager), append-only submission, note length limit, membership changes,
  dashboard scoping, reminder targeting, trend series shape.

The tests that matter most are the ones pinning the deliberate decisions above:
that a second submission appends rather than overwrites, that a non-member gets
404, that a plain member cannot change membership, and that someone *else*
being late does not put a reminder on *your* dashboard.

---

## 10. Running it

```bash
uv run python manage.py migrate
uv run python manage.py runserver
```

Open <http://127.0.0.1:8000/>, type a name, create a project. No fixtures, no
superuser, no seed step — the first name typed is a working account.

For anything beyond local use, set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, and
`DJANGO_ALLOWED_HOSTS`. All three read from the environment.

---

## 11. What this architecture makes easy later

The §6 deferrals were checked against this structure:

| Deferred item | Cost to add |
|---|---|
| Real auth | Install `contrib.auth`, add `auth_user_id` to `User`, swap `identity.py`. The rest is untouched — no view reads a password |
| Per-project reminder thresholds | Nullable `Project.stale_after_days`, falling back to the setting |
| CSV / digest export | New view over existing queries. Append-only rows make this trivially correct |
| Visibility tiers | A `visibility` column on `FeedbackEntry` plus a filter in two querysets |
| Custom form fields | The real schema change — would need an entry-attributes table |

The append-only model is what keeps most of these cheap: there is no update
path to audit, so any new read is just a new query.
