import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { ApiError, getSession, joinSession, type Role, type Session } from "@/lib/api";
import { saveIdentity } from "@/lib/identity";

export const Route = createFileRoute("/join/$sessionId")({
  head: () => ({
    meta: [
      { title: "Join the interview — Loopboard" },
      { name: "description", content: "Enter your display name to join the shared design board." },
      { property: "og:title", content: "Join the interview — Loopboard" },
      { property: "og:description", content: "Enter your name to join the live design board." },
    ],
  }),
  component: JoinPage,
});

function JoinPage() {
  const { sessionId } = Route.useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState<Session | null | "loading">("loading");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("candidate");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getSession(sessionId)
      .then(setSession)
      .catch(() => setSession(null));
  }, [sessionId]);

  async function join() {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      // The join response carries the token every later call in this session needs.
      const me = await joinSession({ sessionId, name, role });
      saveIdentity(sessionId, me);
      void navigate({ to: "/session/$sessionId", params: { sessionId } });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not join. Is the API running?");
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-5">
      <div className="panel w-full max-w-md p-6">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Layers className="h-5 w-5" />
        </span>
        {session === "loading" && <p className="mt-5 text-sm text-muted-foreground">Checking the link…</p>}
        {session === null && (
          <>
            <h1 className="mt-5 text-xl font-semibold">This link isn't valid</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              The session may have been deleted. Ask your interviewer for a fresh link.
            </p>
          </>
        )}
        {session && session !== "loading" && (
          <>
            <h1 className="mt-5 text-xl font-semibold">{session.title}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Hosted by {session.hostName}
              {session.status === "ended" ? " · this session has ended (read-only)" : ""}
            </p>

            <label className="mt-6 block">
              <span className="label-caps">Your display name</span>
              <input
                autoFocus
                className="field mt-1"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void join()}
                placeholder="Jordan"
              />
            </label>

            <div className="mt-4">
              <span className="label-caps">Join as</span>
              <div className="mt-1 flex gap-2">
                {(["candidate", "observer"] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRole(r)}
                    className={`btn-base flex-1 ${role === r ? "btn-primary" : "btn-ghost"}`}
                  >
                    {r === "candidate" ? "Candidate (can edit)" : "Observer (view only)"}
                  </button>
                ))}
              </div>
            </div>

            {error && <p className="mt-4 text-sm text-destructive">{error}</p>}

            <button type="button" className="btn-base btn-primary mt-6 w-full" onClick={join} disabled={busy}>
              {busy ? "Joining…" : "Join session"}
            </button>
            <p className="mt-3 text-xs text-muted-foreground">No account needed.</p>
          </>
        )}
      </div>
    </main>
  );
}
