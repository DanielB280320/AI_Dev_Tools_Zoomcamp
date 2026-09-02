# Weekly Project Feedback Tool

A shared dashboard where team members log a colour status and a short note on
the projects they're part of. Updated whenever something changes — not on a
forced weekly schedule.

- **Spec:** [`_docs/plan.md`](_docs/plan.md)
- **Architecture and design decisions:** [`_docs/architecture.md`](_docs/architecture.md)

## Run it

```bash
uv run python manage.py migrate
uv run python manage.py runserver
```

Open <http://127.0.0.1:8000/> and type a name. There is no password — this is
an internal, trust-based tool by design (see spec §2.1).

## Test it

```bash
uv run python manage.py test
```

## Stack

Django 6.1 · SQLite · server-rendered templates · Chart.js for the trend view.
`django.contrib.auth` is deliberately not installed — see
[architecture §1.1](_docs/architecture.md#11-the-one-significant-deviation-no-djangocontribauth).
