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

### Configuration

Settings are environment variables, passed with `-e`:

```bash
docker run -d --name loopboard -p 8000:8000 -v loopboard-data:/data \
  -e LOOPBOARD_SEED=0 \
  loopboard
```

| Variable                  | Default (in the image)            | Purpose                              |
| ------------------------- | --------------------------------- | ------------------------------------ |
| `LOOPBOARD_DATABASE_URL`  | `sqlite:////data/loopboard.db`    | Where the data lives                 |
| `LOOPBOARD_SEED`          | `1`                               | Seed demo data into an empty database |

See `backend/app/config.py` for the rest.

## Local development

Without Docker, the `Makefile` runs the API and the frontend dev server
separately (needs `uv` and Node.js). Run `make` for the list of targets; the
usual ones are:

```bash
make install   # install backend (uv) and frontend (npm) dependencies
make dev       # API on :8000 and frontend on :8080, Ctrl-C stops both
make test      # backend tests
```

See `backend/README.md` and `frontend/README.md` for more.
