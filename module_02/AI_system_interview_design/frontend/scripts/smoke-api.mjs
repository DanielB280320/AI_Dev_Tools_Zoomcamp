/**
 * End-to-end smoke test for the backend client.
 *
 * Drives the real `src/lib/api.ts` and `src/lib/identity.ts` against a running
 * backend, so it catches what `tsc` cannot: a wrong path, a missing token, a
 * payload the server rejects. The browser APIs those modules need are shimmed —
 * `localStorage` with a Map, `EventSource` with fetch plus an SSE frame parser.
 *
 *   make dev                       # or: make api
 *   node frontend/scripts/smoke-api.mjs
 *
 * Expects the backend's seeded demo account on http://localhost:8000.
 */
import { createJiti } from "jiti";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..", "src");

/* ------------------------------ browser shims ----------------------------- */

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  clear: () => store.clear(),
};
globalThis.window = { localStorage: globalThis.localStorage };

/** Just enough EventSource to prove `subscribeToSession` wires up correctly. */
class MiniEventSource {
  constructor(url) {
    this.listeners = new Map();
    this.closed = false;
    this.controller = new AbortController();
    void this.#run(url);
  }
  addEventListener(kind, fn) {
    this.listeners.set(fn, kind);
  }
  removeEventListener(_kind, fn) {
    this.listeners.delete(fn);
  }
  close() {
    this.closed = true;
    this.controller.abort();
  }
  async #run(url) {
    let response;
    try {
      response = await fetch(url, { signal: this.controller.signal });
    } catch {
      return;
    }
    if (!response.ok) return;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (!this.closed) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let end;
        while ((end = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, end);
          buffer = buffer.slice(end + 2);
          const name = /^event: (.+)$/m.exec(frame)?.[1];
          if (!name) continue; // a comment line: ": keepalive"
          for (const [fn, kind] of this.listeners) if (kind === name) fn();
        }
      }
    } catch {
      /* aborted by close() */
    }
  }
}
globalThis.EventSource = MiniEventSource;

/* -------------------------------- the suite ------------------------------- */

const jiti = createJiti(import.meta.url, { alias: { "@": SRC } });
const api = await jiti.import(`${SRC}/lib/api.ts`);
const identity = await jiti.import(`${SRC}/lib/identity.ts`);

const results = [];
let failures = 0;

function check(label, ok, detail = "") {
  results.push(`${ok ? "  ok" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures++;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const failed = (promise) => promise.then(() => null).catch((error) => error);

let sessionId = "";
/** api.ts reads the session token from storage, so "acting as" is just a write. */
const actAs = (participant) => identity.saveIdentity(sessionId, participant);

// Interviewer sign-in — the account-scoped half of the auth story.
const auth = await api.signIn({ email: "alex@loopboard.dev", password: "loopboard-demo" });
identity.saveAuth(auth);
check("signIn returns a token and the account", !!auth.token && !!auth.interviewer.email);
check(
  "a wrong password is rejected",
  (await failed(api.signIn({ email: "alex@loopboard.dev", password: "nope" })))?.status === 401,
);

const dashboard = await api.listSessions();
check(
  "listSessions comes back newest-first",
  dashboard.every((s, i) => i === 0 || dashboard[i - 1].createdAt >= s.createdAt),
  `${dashboard.length} sessions`,
);

// Create a board and join it as the host, exactly as the dashboard does.
const session = await api.createSession({ title: "  Smoke test board  ", hostName: " Alex " });
sessionId = session.id;
check(
  "createSession trims its strings",
  session.title === "Smoke test board" && session.hostName === "Alex",
);

const host = await api.joinSession({ sessionId, name: "Alex Rivera", role: "interviewer" });
actAs(host);
check("joinSession returns a participant token", !!host.token);
check(
  "the identity round-trips through localStorage",
  identity.loadIdentity(sessionId)?.token === host.token,
);

const candidate = await api.joinSession({ sessionId, name: "  ", role: "candidate" });
check("a blank display name falls back to Guest", candidate.name === "Guest");
check("colours follow join order", [host.color, candidate.color].join() === "#37d6c3,#f5b83d");

// The join page reads the session before any identity exists.
check("getSession is public", (await api.getSession(sessionId))?.id === sessionId);
check("getSession is null for a dead link", (await api.getSession("nosuchsessionid")) === null);

// Realtime: the host subscribes, the candidate writes, the host is notified.
const seen = [];
const unsubscribe = api.subscribeToSession(sessionId, (kind) => seen.push(kind));
await sleep(400);

const node = {
  type: "shape",
  id: api.newNodeId(),
  kind: "database",
  label: "Postgres",
  x: 10,
  y: 20,
  w: 150,
  h: 96,
  authorId: candidate.id,
};
actAs(candidate);
await api.saveCanvas(sessionId, { nodes: [node] });
await sleep(600);
check(
  "SSE delivered another client's doc event",
  seen.includes("doc"),
  `saw: ${seen.join(",") || "nothing"}`,
);

const canvas = await api.getCanvas(sessionId);
check("the canvas round-trips", canvas.nodes.length === 1 && canvas.nodes[0].id === node.id);
check("client-generated node ids survive", /^n_[a-z2-9]{10}$/.test(node.id));

await api.upsertNodes(sessionId, [{ ...node, label: "Postgres (primary)" }]);
const merged = await api.getCanvas(sessionId);
check(
  "upsertNodes replaces in place",
  merged.nodes.length === 1 && merged.nodes[0].label === "Postgres (primary)",
);
await api.deleteNodes(sessionId, [node.id]);
check("deleteNodes removes it", (await api.getCanvas(sessionId)).nodes.length === 0);

// Presence.
actAs(host);
const roster = await api.listParticipants(sessionId);
check("the roster is in join order", roster.map((p) => p.name).join() === "Alex Rivera,Guest");
await api.publishCursor(sessionId, {
  participantId: host.id,
  name: host.name,
  color: host.color,
  x: -12.5,
  y: 40,
  at: Date.now(),
});
check(
  "a published cursor comes back",
  (await api.listCursors(sessionId)).some((c) => c.participantId === host.id && c.x === -12.5),
);
await api.heartbeat(sessionId, host.id);
check("heartbeat is accepted", true);

// Ending the board freezes it for everyone.
await api.endSession(sessionId);
await sleep(400);
check("SSE delivered the session event", seen.includes("session"));
actAs(candidate);
const frozen = await failed(api.saveCanvas(sessionId, { nodes: [] }));
check(
  "a frozen board refuses writes",
  api.isWriteRejected(frozen),
  frozen && `${frozen.status} ${frozen.code}`,
);
actAs(host);
await api.reopenSession(sessionId);
check("reopen thaws it", (await api.getSession(sessionId))?.canvasLocked === false);

// Observers may watch but not draw.
const observer = await api.joinSession({ sessionId, name: "Priya", role: "observer" });
actAs(observer);
const refused = await failed(api.saveCanvas(sessionId, { nodes: [] }));
check("observers cannot write", refused?.status === 403, refused && refused.code);

// The beforeunload path: no sendBeacon in Node, so this exercises the fallback.
actAs(candidate);
api.leaveSessionOnUnload(sessionId, candidate.id);
await sleep(400);
actAs(host);
check(
  "leaveSessionOnUnload removed the participant",
  !(await api.listParticipants(sessionId)).some((p) => p.id === candidate.id),
);

// A token the server no longer knows has to surface as 401, which is what sends
// the UI back through the join screen.
actAs({ ...host, token: "not-a-real-token" });
check(
  "a dead token raises isUnauthorized",
  api.isUnauthorized(await failed(api.getCanvas(sessionId))),
);
actAs(host);

unsubscribe();
await api.deleteSession(sessionId);
check("deleteSession leaves nothing behind", (await api.getSession(sessionId)) === null);

console.log(results.join("\n"));
console.log(
  failures === 0
    ? `\n${results.length} checks passed against ${api.API_URL}`
    : `\n${failures} of ${results.length} checks FAILED against ${api.API_URL}`,
);
process.exit(failures === 0 ? 0 : 1);
