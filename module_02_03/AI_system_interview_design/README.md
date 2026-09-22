# Loopboard

A collaborative whiteboard for system-design interviews. The backend is a
FastAPI app (`backend/`), the frontend a Vite/React app (`frontend/`).

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
