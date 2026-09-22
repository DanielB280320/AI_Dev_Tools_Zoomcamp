# Loopboard

A collaborative whiteboard for system-design interviews. The backend is a
FastAPI app (`backend/`), the frontend a Vite/React app (`frontend/`).

## Running with Docker Compose

`docker-compose.yaml` starts the two containers the app needs — Postgres and
the app image — and wires them together, which is the shortest path from a
clone to a running app:

```bash
docker compose up --build -d
```

Then open http://localhost:8000. The app waits for Postgres to report healthy,
creates its tables and seeds the demo data on the first start.

```bash
docker compose logs -f app   # follow the server logs
docker compose ps            # what is running
docker compose down          # stop both; the database volume survives
docker compose down -v       # stop both and wipe the data
docker compose up --build -d # rebuild and recreate after a code change
```

The database is published on 5432 so `psql` and `make test-pg` can reach it.
`make db-up` uses that port too, so if you already have that container running,
start this one elsewhere: `PG_PORT=5433 docker compose up -d`. The app's own
port is 8000 — a `make dev` server on the same port shadows the container's,
so stop one before starting the other.

The credentials are development defaults (`sdip` / `sdip` / `sdip`); change
them in the compose file, in both the `db` environment and the app's
`LOOPBOARD_DATABASE_URL`, before exposing the port to anyone else.

### End-to-end tests

`e2e/` holds a Playwright suite that drives this stack through two browsers —
an interviewer creating a session and sharing the link, a candidate joining
and editing the board, and the interviewer seeing the edit arrive live:

```bash
make e2e
```

It runs in the official Playwright container, so it needs nothing beyond
Docker. `e2e/README.md` covers running it from the host, debugging a failure,
and what each step checks.

The next section runs the same containers by hand, which is worth reading for
what each piece does.

## Running with Docker

The `Dockerfile` builds everything into one image: the frontend is built to
static files and served by the API, so a single container runs the whole app.

You need [Docker](https://docs.docker.com/get-docker/) installed and running
(on Windows/WSL, start Docker Desktop and enable its WSL integration).

### Build the image

From this directory (the repository root):

```bash
docker build -t loopboard .
```

### Run the container

```bash
docker run -d --name loopboard -p 8000:8000 -v loopboard-data:/data loopboard
```

- `-p 8000:8000` publishes the app on port 8000. To use another host port,
  change the first number, e.g. `-p 9000:8000`.
- `-v loopboard-data:/data` keeps the SQLite database in a named volume, so
  data survives container restarts and rebuilds.

Then open:

| URL                            | What                   |
| ------------------------------ | ---------------------- |
| http://localhost:8000          | The app                |
| http://localhost:8000/docs     | Interactive API docs   |
| http://localhost:8000/health   | Health check           |

Sign in with the seeded demo account **alex@loopboard.dev / loopboard-demo**
(also `sam@loopboard.dev`). Candidates need no account — they join with a link
and a display name.

### Managing the container

```bash
docker logs -f loopboard     # follow the server logs
docker stop loopboard        # stop it
docker start loopboard       # start it again
docker rm -f loopboard       # remove the container (the data volume is kept)
docker volume rm loopboard-data   # wipe the data; the next start re-seeds the demo data
```

After changing the code, rebuild the image and recreate the container:

```bash
docker build -t loopboard .
docker rm -f loopboard
docker run -d --name loopboard -p 8000:8000 -v loopboard-data:/data loopboard
```

### Running it against Postgres

The image defaults to SQLite on the mounted volume, which needs no setup. To put
the data in Postgres instead, start one and point `LOOPBOARD_DATABASE_URL` at it —
no `-v` needed, since the data is then the database's problem:

```bash
docker run -d --name interview-canvas-db \
  -e POSTGRES_USER=sdip -e POSTGRES_PASSWORD=sdip -e POSTGRES_DB=sdip \
  -p 5432:5432 -v interview-canvas-pgdata:/var/lib/postgresql/data \
  postgres:16-alpine

docker run -d --name loopboard -p 8000:8000 \
  --add-host=host.docker.internal:host-gateway \
  -e LOOPBOARD_DATABASE_URL=postgresql://sdip:sdip@host.docker.internal:5432/sdip \
  loopboard
```

`localhost` inside a container is that container, so the app reaches a Postgres
published on the host through `host.docker.internal`, which `--add-host` defines.
Put both on a user-defined network instead and the container name works directly:

```bash
docker network create loopboard-net
docker network connect loopboard-net interview-canvas-db
docker run -d --name loopboard -p 8000:8000 --network loopboard-net \
  -e LOOPBOARD_DATABASE_URL=postgresql://sdip:sdip@interview-canvas-db:5432/sdip \
  loopboard
```

> **The host in the URL depends on where the server runs.** A container name
> (`interview-canvas-db`) resolves *only* inside a Docker network — it is not a
> hostname your machine knows. Running the server outside Docker, with `make dev`
> or `make api-pg`, the URL is `…@localhost:5432/…`. Getting this wrong is the one
> failure the server explains on startup rather than leaving to a traceback.

The tables are created and the demo data seeded on first start, exactly as with
SQLite. `backend/README.md` covers the rest — connection pooling, what changes
between the two databases, and `make db-up` / `make api-pg` / `make test-pg` for
running the same thing without Docker.

### Configuration

Settings are environment variables, passed with `-e`:

```bash
docker run -d --name loopboard -p 8000:8000 -v loopboard-data:/data \
  -e LOOPBOARD_SEED=0 \
  loopboard
```

| Variable                  | Default (in the image)            | Purpose                              |
| ------------------------- | --------------------------------- | ------------------------------------ |
| `LOOPBOARD_DATABASE_URL`  | `sqlite:////data/loopboard.db`    | Where the data lives — a SQLite path, or a `postgres://` / `postgresql://` URL |
| `LOOPBOARD_SEED`          | `1`                               | Seed demo data into an empty database |

See `backend/app/config.py` for the rest.

## Deploying to AWS

`deploy/` holds a CloudFormation template that puts this stack on one EC2
instance with Caddy terminating TLS in front of it:

```bash
aws cloudformation deploy --stack-name loopboard \
  --template-file deploy/loopboard.cfn.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides VpcId=vpc-... SubnetId=subnet-... DomainName=example.com
```

One instance, deliberately — the SSE broker is per-process, so a second one
would serve clients that never hear about the first one's edits. `deploy/README.md`
covers that, the DNS step, redeploying and the running cost.

## Local development

Without Docker, the `Makefile` runs the API and the frontend dev server
separately (needs `uv` and Node.js). Run `make` for the list of targets; the
usual ones are:

```bash
make install   # install backend (uv) and frontend (npm) dependencies
make dev       # API on :8000 and frontend on :8080, Ctrl-C stops both
make test      # backend tests (SQLite)

make db-up     # a local Postgres container
make api-pg    # the API against it, instead of the SQLite file
make test-pg   # the same backend tests against it
```

See `backend/README.md` and `frontend/README.md` for more.
