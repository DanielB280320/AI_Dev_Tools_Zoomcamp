import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Layers, LogOut, Plus, Trash2 } from "lucide-react";
import {
  createSession,
  deleteSession,
  isUnauthorized,
  joinSession,
  listSessions,
  signOut,
  type Interviewer,
  type Session,
} from "@/lib/api";
import { clearAuth, loadAuth, loadHostName, saveHostName, saveIdentity } from "@/lib/identity";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Interviewer dashboard — Loopboard" },
      {
        name: "description",
        content:
          "Create a system design interview session, share the join link, and reopen past boards for scoring.",
      },
      { property: "og:title", content: "Interviewer dashboard — Loopboard" },
      {
        property: "og:description",
        content: "Create a session, share a link, and run the interview on a shared canvas.",
      },
    ],
  }),
  component: Dashboard,
});

function Dashboard() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [title, setTitle] = useState("");
  const [hostName, setHostName] = useState("");
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Deliberately not seeded from localStorage: the server render cannot see it,
  // and differing first renders would be a hydration mismatch. The effect fills it.
  const [account, setAccount] = useState<Interviewer | null>(null);

  /** The dashboard endpoints are account-scoped, so sign-in comes first. */
  const requireSignIn = useCallback(() => {
    clearAuth();
    setAccount(null);
    void navigate({ to: "/signin", replace: true });
  }, [navigate]);

  const refresh = useCallback(async () => {
    try {
      setSessions(await listSessions());
      setError(null);
    } catch (cause) {
      // The backend keeps tokens in memory, so a restart invalidates ours.
      if (isUnauthorized(cause)) return requireSignIn();
      setError(cause instanceof Error ? cause.message : "Could not load sessions.");
      setSessions([]);
    }
  }, [requireSignIn]);

  useEffect(() => {
    const auth = loadAuth();
    if (!auth) return requireSignIn();
    setAccount(auth.interviewer);
    setHostName(loadHostName() || auth.interviewer.name);
    void refresh();
  }, [refresh, requireSignIn]);

  async function handleCreate() {
    if (creating) return;
    setCreating(true);
    setError(null);
    saveHostName(hostName);
    try {
      const session = await createSession({ title, hostName });
      // Join our own session to get the participant token the board needs.
      const me = await joinSession({
        sessionId: session.id,
        name: hostName || "Interviewer",
        role: "interviewer",
      });
      saveIdentity(session.id, me);
      void navigate({ to: "/session/$sessionId", params: { sessionId: session.id } });
    } catch (cause) {
      if (isUnauthorized(cause)) return requireSignIn();
      setError(cause instanceof Error ? cause.message : "Could not create the session.");
      setCreating(false);
    }
  }

  const joinUrl = (id: string) =>
    typeof window === "undefined" ? `/join/${id}` : `${window.location.origin}/join/${id}`;

  return (
    <main className="mx-auto min-h-screen w-full max-w-5xl px-5 py-10">
      <header className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Layers className="h-5 w-5" />
        </span>
        <div>
          <h1 className="text-2xl font-semibold">Loopboard</h1>
          <p className="text-sm text-muted-foreground">
            Live system design interviews on a shared architecture board.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {account && (
            <span className="font-mono text-xs text-muted-foreground">{account.email}</span>
          )}
          <button
            type="button"
            className="btn-base btn-ghost"
            title="Sign out"
            onClick={async () => {
              await signOut().catch(() => {});
              requireSignIn();
            }}
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      </header>

      <section className="panel mt-8 p-5">
        <h2 className="text-lg font-semibold">New interview session</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <label className="block">
            <span className="label-caps">Session title</span>
            <input
              className="field mt-1"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Design a URL shortener — Senior BE"
            />
          </label>
          <label className="block">
            <span className="label-caps">Your name</span>
            <input
              className="field mt-1"
              value={hostName}
              onChange={(e) => setHostName(e.target.value)}
              placeholder="Alex (interviewer)"
            />
          </label>
          <button type="button" className="btn-base btn-primary mt-6 h-10" onClick={handleCreate} disabled={creating}>
            <Plus className="h-4 w-4" />
            {creating ? "Creating…" : "Start session"}
          </button>
        </div>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      </section>

      <section className="mt-10">
        <h2 className="text-lg font-semibold">Sessions</h2>
        {sessions === null && <p className="mt-3 text-sm text-muted-foreground">Loading…</p>}
        {sessions?.length === 0 && (
          <p className="mt-3 text-sm text-muted-foreground">
            No sessions yet. Start one above and share the join link with your candidate.
          </p>
        )}
        <ul className="mt-4 space-y-2">
          {sessions?.map((s) => (
            <li key={s.id} className="panel flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium">{s.title}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 font-mono text-[10px] uppercase ${
                      s.status === "live"
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {s.status}
                  </span>
                </div>
                <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                  {new Date(s.createdAt).toLocaleString()} · host {s.hostName}
                </p>
              </div>
              <button
                type="button"
                className="btn-base btn-ghost"
                onClick={() => {
                  void navigator.clipboard?.writeText(joinUrl(s.id));
                  setCopied(s.id);
                  setTimeout(() => setCopied(null), 1600);
                }}
              >
                {copied === s.id ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied === s.id ? "Copied" : "Join link"}
              </button>
              <Link to="/session/$sessionId" params={{ sessionId: s.id }} className="btn-base btn-primary">
                Open board
              </Link>
              <button
                type="button"
                className="btn-base btn-danger"
                onClick={async () => {
                  if (!window.confirm("Delete this session and its board?")) return;
                  try {
                    await deleteSession(s.id);
                  } catch (cause) {
                    if (isUnauthorized(cause)) return requireSignIn();
                    setError(cause instanceof Error ? cause.message : "Could not delete.");
                  }
                  await refresh();
                }}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      </section>

      <p className="mt-12 font-mono text-xs text-muted-foreground">
        Sessions, presence and boards live in the backend (src/lib/api.ts → FastAPI); live updates
        arrive over Server-Sent Events. Open a join link in a second tab or browser to see the sync
        and cursors.
      </p>
    </main>
  );
}
