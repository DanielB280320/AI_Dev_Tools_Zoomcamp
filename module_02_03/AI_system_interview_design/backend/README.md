# Loopboard backend

FastAPI implementation of [`../openapi.yaml`](../openapi.yaml) — the backend the
Loopboard frontend expects. Storage is a SQL database through SQLAlchemy —
SQLite by default so a fresh clone needs no setup, Postgres by setting one
environment variable — seeded with demo data while it is still empty, so the
frontend has something to render on the first run and keeps it afterwards.

## Run it

From the repo root, via the Makefile (`make` alone lists every target):

```bash
make install   # uv sync + npm install
make api       # this backend, with reload, on :8000
make dev       # backend and frontend together
make test      # this suite
```

On Postgres instead of the default SQLite file — `make db-up` starts one locally:

```bash
make db-up     # postgres:16-alpine in docker, waits until it is ready
make api-pg    # this backend against it
make test-pg   # this suite against it
```

Or directly:

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

* Interactive docs: <http://localhost:8000/docs>
* Liveness: <http://localhost:8000/health>

The frontend's `vite dev` serves on `:8080`, which the default CORS list allows;
override it with `LOOPBOARD_CORS_ORIGINS`.

## Tests

```bash
uv run pytest -q     # SQLite
make test-pg         # the same tests against Postgres
```

Nothing in the suite names a dialect, so both runs are the same 229 tests; the
database comes from `LOOPBOARD_TEST_DATABASE_URL`, and defaults to a throwaway
SQLite file. See [*Running on Postgres*](#running-on-postgres).

## Layout

| Module | Responsibility |
|---|---|
| `app/models.py` | Wire models, one per schema in the contract |
| `app/store.py` | Every query and write the API makes, one method each: ids, palette, TTLs |
| `app/tables.py` | The schema — one mapped class per table, and the records that come back |
| `app/db.py` | Engine, session scope and the only dialect-aware code in the app |
| `app/auth.py` | Password hashing, token issue/resolve, the authz dependencies |
| `app/events.py` | The `doc` / `presence` / `session` notification broker behind SSE |
| `app/seed.py` | Demo accounts, sessions and boards |
| `app/config.py` | Env-overridable settings (TTLs, limits, CORS, seeding) |
| `app/errors.py` | The `{"error": code, "message": …}` shape, on every failure path |
| `app/routers/` | One module per tag: sessions, participants, cursors, canvas, events, auth |

## Storage

`LOOPBOARD_DATABASE_URL` decides where the data lives. SQLite by default, so a fresh
clone runs with no setup; Postgres for anything with more than one server process.

```bash
LOOPBOARD_DATABASE_URL=sqlite:///./loopboard.db            # a file (the default shape)
LOOPBOARD_DATABASE_URL=sqlite://                           # in memory, lost on exit
LOOPBOARD_DATABASE_URL=postgres://user:pw@host/loopboard   # Postgres
LOOPBOARD_DATABASE_URL=postgresql://user:pw@host/loopboard # the same thing
```

`postgres://` and `postgresql://` are both rewritten to `postgresql+psycopg://` on the way
in, because SQLAlchemy's default driver for a bare Postgres URL is psycopg2 and the one
installed here is psycopg 3. So the URL copied out of a hosting dashboard, a `psql`
invocation or a `docker run` works unedited. A URL that names its own driver is left alone.

Nothing outside `app/db.py` names a dialect. The schema uses only portable types —
`VARCHAR`, `BIGINT` for the epoch-millisecond timestamps, `DOUBLE`, `BOOLEAN`, and `JSON`
(`JSONB` on Postgres) for a canvas node — and the enums are stored as their wire values in
a `VARCHAR` rather than a native database enum, so adding a role never needs a migration.

| Table | Holds |
|---|---|
| `accounts` | Interviewers, with a PBKDF2 password hash |
| `tokens` | Issued bearer tokens and their scope |
| `sessions` | The boards, their status and lock |
| `participants` | Membership, join order, colour, `last_seen` |
| `cursors` | The latest position published by each participant |
| `canvas_nodes` | One row per node: id, `position` (z-order) and the node as JSON |

Tables are created at startup with `create_all`, which is enough while the schema only
grows. The first column that changes shape is the point to add Alembic.

* `LOOPBOARD_DB_ECHO=1` logs every statement.
* `make db-reset` deletes the default SQLite file, so the next start re-seeds.

### Running on Postgres

`make db-up` starts a local container and waits for it to accept connections:

```bash
make db-up        # postgres:16-alpine as `interview-canvas-db`, on :5432
make api-pg       # the API against it, instead of the SQLite file
make test-pg      # the whole test suite against it
make db-psql      # a psql shell
make db-reset-pg  # drop every table, so the next start re-seeds
make db-down      # stop it; the data survives in its volume
```

The container is the one below, and `db-up` is idempotent — it starts it, resumes it, or
reports that it is already up. Override `PG_USER`, `PG_PORT`, `PG_DB` … to change it, or
`PG_URL` alone to point `api-pg` and `test-pg` at a database this Makefile did not start.

```bash
docker run -d --name interview-canvas-db \
  -e POSTGRES_USER=sdip -e POSTGRES_PASSWORD=sdip -e POSTGRES_DB=sdip \
  -p 5432:5432 -v interview-canvas-pgdata:/var/lib/postgresql/data \
  postgres:16-alpine
```

The test suite is dialect-agnostic — nothing in it names SQLite — so `make test-pg` is the
same 229 tests against Postgres. It empties the database on the way in and out, so point
it only at a database whose contents are expendable.

### What differs between the two

`app/db.py` holds every dialect-specific decision.

**Connections.** SQLite gets `check_same_thread=False`, `foreign_keys=ON`, WAL and a busy
timeout, and an in-memory URL gets a single shared connection. Postgres gets a real pool
instead — `pool_pre_ping` to replace a connection a proxy or a restart closed underneath
it, `pool_recycle` to stay under an idle timeout, a connect timeout so an unreachable
server fails fast rather than hanging a request, and `application_name=loopboard` so a
held connection is identifiable in `pg_stat_activity`. All four are tunable:
`LOOPBOARD_DB_POOL_SIZE` (5), `LOOPBOARD_DB_MAX_OVERFLOW` (10),
`LOOPBOARD_DB_POOL_RECYCLE_SECONDS` (1800, 0 to disable),
`LOOPBOARD_DB_CONNECT_TIMEOUT_SECONDS` (10).

**Startup.** With SQLite the server is the only process, so "create the tables, then seed
if empty" cannot go stale between the question and the answer. A Postgres deployment runs
several workers, and two that both find no tables — or both find no sessions — will both
try to seed, and the loser dies on a duplicate `accounts.email`. Startup therefore runs
under `bootstrap_lock()`, a `pg_advisory_lock` on Postgres and a no-op elsewhere: the
second worker waits, then finds the database already seeded and seeds nothing.

**Read-then-write.** Two places pick "the next number" — a join's place in the roster,
which decides its colour, and a cursor's place in the list. Neither dialect makes that
safe on its own:

* A first cursor publish was a read followed by an insert, which on Postgres lets two
  participants both find no row and both insert, and one of them takes a primary key
  violation. `put_cursor` is now a single `INSERT … ON CONFLICT DO UPDATE`, which both
  dialects support and which has no window to lose.
* A join counts the roster and then inserts. On Postgres the joins of one session queue
  behind a `FOR UPDATE` on the session row, which serialises them across worker processes.
  SQLite needs a different fix and *did have this bug*: a transaction begins deferred and
  takes no lock until its first write, so concurrent joins could read the same count and
  land on the same colour. `serialized_write()` closes it with a process-local lock, which
  is sufficient there because SQLite is the single-process case by definition.

`tests/test_concurrency.py` covers both, and runs under `make test` and `make test-pg`.

## Authentication

Two bearer schemes, as the contract describes:

* **`interviewerAuth`** — account-scoped. `POST /auth/login` returns it. Required by
  `POST /sessions`, `GET /sessions` and `DELETE /sessions/{id}`.
* **`participantAuth`** — session-scoped. Issued by `POST /sessions/{id}/participants`
  (join) and required by everything else under `/sessions/{id}/…`. The token is opaque;
  the session id, participant id and role live in the server-side token record.

Unauthenticated: `GET /sessions/{id}` (the join page validates the link before any
identity exists) and the join itself.

Passwords are stored as salted **PBKDF2-HMAC-SHA256** digests
(`pbkdf2_sha256$<rounds>$<salt>$<digest>`, 600 000 rounds by default, constant-time
compare). A login against an unknown email still pays the hashing cost, so response
time does not reveal which emails exist.

### Sign-in is an addition to the contract

`openapi.yaml` defines `interviewerAuth` but no operation that issues one, because at the
time it was written the frontend had no sign-in screen ("Gap to close" in the spec).
`POST /auth/register`, `POST /auth/login`, `GET /auth/me` and `POST /auth/logout` fill that
gap, and the frontend's `/signin` route now uses them. No operation from the contract was
changed.

### Demo credentials

| Email | Password | Sessions |
|---|---|---|
| `alex@loopboard.dev` | `loopboard-demo` | 4 — two live with drawn boards, one ended, one empty |
| `sam@loopboard.dev` | `loopboard-demo` | 1 — proves `GET /sessions` is scoped to the owner |

Sign in through the frontend's `/signin`, or straight against the API:

```bash
curl -s localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"email":"alex@loopboard.dev","password":"loopboard-demo"}'
```

Candidates and observers need no account: they join with a link and a display name.

Seeded session ids are fixed so you can deep-link straight to a board:

| Session | Id |
|---|---|
| URL shortener (live, 3 participants, cursors) | `k7m2xp9qrt4wnb3d` |
| Group chat backend (live, 2 participants) | `q4ztv8hdr2mkp6sn` |
| Distributed rate limiter (**ended**, frozen) | `b3wn7cfk9xqm2rvd` |
| Untitled interview (live, empty board) | `t8hq3mz5xkbn7wrd` |
| Feature flag service (owned by Sam) | `z6rkp2mq4xhtn9bw` |

Seeding happens only while the database is empty, so a restart keeps whatever the last
run left behind. Start empty instead with `LOOPBOARD_SEED=0`, or wipe the file with
`make db-reset`.

## Contract behaviour worth knowing

* **Milliseconds everywhere** — `createdAt`, `endedAt`, `lastSeen`, `at`.
* **`GET /sessions` is pre-sorted** by `createdAt` descending, and returns only the
  caller's own sessions.
* **Cursors expire**: `GET /cursors` omits anything older than 15 s.
* **Participants expire**: a roster read drops anyone who missed ~15 s of heartbeats
  (the frontend beats every 4 s). Disable with `LOOPBOARD_PRUNE_STALE_PARTICIPANTS=0`.
* **Colours are server-assigned** from the fixed palette, cycling by join order.
* **Empty strings fall back**: session title → `Untitled interview`, host name →
  `Interviewer`, participant name → `Guest`.
* **A missing session is always a 404**, never a 200 with an empty body.
* **Writes are rejected** with `409 canvas_locked` on an ended or locked board, and
  `403 forbidden_role` for observers.
* **Z-order is array order**: a whole-document `PUT` is stored verbatim, and
  `PATCH /canvas/nodes` replaces an existing node *in place* rather than moving it to
  the end.
* **Heartbeats emit no event.** Every other mutation emits `doc`, `presence` or
  `session` — and a canvas write or cursor publish skips the client that caused it,
  so nobody re-fetches their own save.
* **Leave is sendBeacon-friendly**: `POST /sessions/{id}/participants/{pid}/leave`
  accepts the token in the body (`{"token": "…"}`) because a beacon cannot set headers.
  Leave and heartbeat also tolerate a participant who is already off the roster,
  answering `204` rather than a 401 loop.

## Realtime

`GET /sessions/{id}/events` is an SSE stream carrying exactly three event names —
`doc`, `presence`, `session` — with `{"sessionId": "…"}` as the payload. Events are
*change notifications*: on receipt the client re-fetches the canvas, the roster or the
session. A `: keepalive` comment goes out every ~20 s. Because `EventSource` cannot set
headers, the stream also accepts `?token=…`.

## Known limits

* **The SSE broker is still in-process, which is what actually caps this at one
  worker.** Moving to Postgres makes the *data* safe to share — concurrent startup,
  joins and cursor publishes are all handled — but a `doc` / `presence` / `session`
  notification still only reaches subscribers attached to the same process. Two workers
  means two clients on different workers never hear about each other's edits. The next
  step for horizontal scaling is a shared bus: Postgres `LISTEN/NOTIFY` is already
  reachable from here, Redis pub/sub otherwise.
* **Blocking database calls in an async handler.** Barely matters against a local SQLite
  file; against Postgres every call is a network round trip taken on the event loop, so
  this is now the first thing to fix under load — either the async driver
  (`postgresql+asyncpg`, which the URL already supports) or sync endpoints run in the
  threadpool.
* **No migrations.** `create_all` on startup, no Alembic yet. On Postgres that also means
  a constraint added to an existing table is silently not applied — `create_all` creates
  missing tables, it never alters one.
* **Session `seq` is not contended-safe.** Two sessions created by one owner inside the
  same millisecond can take the same `seq`, so the order `GET /sessions` lists those two
  in is arbitrary. Unlike the participant equivalent this is only a tiebreaker, and
  nothing user-visible depends on it, so it is left alone.
* **Whole-document canvas writes are last-write-wins.** Two people dragging at once means
  the slower client's document overwrites the faster one's. This is the MVP contract; the
  node-level operations are the seam where a CRDT/op channel should land.
* **No rate limiting.** Canvas writes (120 ms debounce), cursors (~11 Hz) and heartbeats
  (4 s) are all unthrottled server-side.
