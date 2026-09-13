# AI System Interview Design

Implement exactly the screenshot and nothing else

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/f3d40d40-a265-4aa0-bc06-8da97a37dc92).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Signing in

The app opens on `/signin`, because creating and listing sessions is account-scoped. The
backend seeds two interviewer accounts, both with the password **`loopboard-demo`**:

| Email | Password | What it owns |
|---|---|---|
| `alex@loopboard.dev` | `loopboard-demo` | 4 boards — two live and drawn on, one ended, one empty |
| `sam@loopboard.dev` | `loopboard-demo` | 1 board — proves the dashboard is per-account |

"Create an account instead" on the same screen registers a new interviewer (any email, 8+
character password). **Candidates and observers need no credentials at all** — they open a
join link and type a display name.

The accounts come from the backend's seed data, which is written to its database the first
time it starts — so they, and anything you create afterwards, survive a restart. Start with
no seed data at all using `LOOPBOARD_SEED=0`, or wipe the board with `make db-reset`.

## Backend

The app talks to the FastAPI backend in [`../backend`](../backend) — sessions, presence,
the canvas document and live updates all live there. Run both with `make dev` from the repo
root; the client defaults to `http://localhost:8000` and honours `VITE_API_URL`.

What the wiring looks like:

- `src/lib/api.ts` — one function per backend operation, plus `subscribeToSession`, which is
  a Server-Sent Events stream of `doc` / `presence` / `session` notifications. Events carry no
  state: each one is a cue to re-fetch.
- `src/lib/identity.ts` — the two credentials in `localStorage`: the participant token for
  each session (written at join time) and the interviewer sign-in for the dashboard. `api.ts`
  reads both, so call sites never pass tokens around.
- `/signin` — interviewer email + password. Candidates still need no account: a link and a
  display name is the whole join flow.

`node scripts/smoke-api.mjs` (or `make smoke`) drives the real client module against a running
backend and prints a pass/fail line per behaviour — useful after touching either side.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
