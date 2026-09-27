# End-to-end tests

Playwright tests that drive the real app — the two containers in
`../docker-compose.yaml` (Postgres, and the app image serving the built
frontend) — through two browsers at once.

## What is covered

`tests/interview-session.spec.ts` walks one interview through, as six steps
that show up by name in the report and the trace:

1. The interviewer signs in (with the seeded demo account).
2. They create an interview session and land on its board.
3. They click **Copy join link**; the test reads the link back off the
   clipboard and checks it points at this session.
4. A candidate opens that link in a **separate browser context** — no shared
   cookies or localStorage, so nothing reaches it except through the API — and
   joins. The interviewer's roster shows them.
5. The candidate drags an *API Gateway* block onto the board and renames it to
   a marker unique to this run.
6. The interviewer's board shows the marker. Nothing is clicked on that side:
   the change can only have arrived over the Server-Sent Events stream.

Each run creates its own session, so runs don't interfere and the database
never needs resetting.

## Running

From the repository root:

```bash
make e2e         # in the official Playwright container — nothing to install but Docker
make e2e-local   # from the host, faster, but needs Chromium's system libraries
```

`make e2e` is `docker compose -f docker-compose.yaml -f docker-compose.e2e.yaml
run --rm e2e`. Compose starts Postgres and the app, waits until both report
healthy, then runs the suite in a container sharing the app's network. The
stack is left running afterwards; `make down` stops it.

`make e2e-local` (or `npm test` in this directory) starts the stack itself with
`docker compose up --build` if nothing answers on `:8000`, and reuses it if
something does. Chromium needs libraries like `libnss3` and `libnspr4`;
`sudo npx playwright install-deps chromium` installs them. Without them the
browser fails to launch with `error while loading shared libraries`, and
`make e2e` is the way to go.

Narrow or debug a run through `ARGS`:

```bash
make e2e ARGS='--grep "canvas edit"'
make e2e-local ARGS='--headed'      # watch it, on the host
make e2e-local ARGS='--debug'       # step through it in the inspector
```

A failing test leaves a trace, a video and screenshots under
`test-results/`; `npx playwright show-trace test-results/<test>/trace.zip`
replays it step by step.

## Configuration

| Variable                   | Default               | Purpose |
| -------------------------- | --------------------- | ------- |
| `E2E_BASE_URL`             | `http://localhost:8000` | Where the app is. Setting it means "already running": the suite then never touches Docker. |
| `E2E_INTERVIEWER_EMAIL`    | `alex@loopboard.dev`  | The account the interviewer signs in with |
| `E2E_INTERVIEWER_PASSWORD` | `loopboard-demo`      | …and its password |
| `E2E_USER`                 | `1000:1000`           | `make e2e` only: the uid:gid the container writes `test-results/` as |

## Two things that look odd and are deliberate

**The runner shares the app container's network namespace**
(`network_mode: "service:app"`) and reaches it as `http://localhost:8000`.
Step 3 reads the clipboard, and the clipboard API exists only in a secure
context — which plain http is on `localhost` and nowhere else. The compose
service name doesn't work either way: `http://app:8000` is upgraded to https by
Chrome, because `.app` is on its HSTS preload list.

**Step 5 drags from the palette rather than using the Text tool.** The Text
tool's inline editor opens on pointer-down and saves on blur, and the rest of
the click that placed it moves the focus away before anything can be typed —
so the node is saved empty and discarded. Playwright's click is real input
events, so this probably happens to people too; it is worth trying by hand
(`InterviewCanvas.tsx`, the `tool === "text"` branch of `onPointerDown`). The
palette drag and the inspector's name field are the path the board itself
advertises, and they don't depend on that.

## Keeping versions in step

The image tag in `../docker-compose.e2e.yaml`
(`mcr.microsoft.com/playwright:v1.63.0-noble`) has to match the
`@playwright/test` version in `package.json`: the image brings the browsers,
the mounted `node_modules` brings the runner, and each version expects its own
browser build. Bump both together.
