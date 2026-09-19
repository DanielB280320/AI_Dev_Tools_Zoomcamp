import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy, Layers, LogOut, Radio, Square, UserMinus } from "lucide-react";
import type { CanvasNode } from "@/lib/canvas-types";
import {
  endSession,
  getCanvas,
  getSession,
  heartbeat,
  isUnauthorized,
  isWriteRejected,
  leaveSession,
  leaveSessionOnUnload,
  listCursors,
  listParticipants,
  publishCursor,
  removeParticipant,
  reopenSession,
  saveCanvas,
  subscribeToSession,
  type CursorState,
  type JoinedParticipant,
  type Participant,
  type Session,
} from "@/lib/api";
import { clearIdentity, loadIdentity } from "@/lib/identity";
import { InterviewCanvas } from "@/components/canvas/InterviewCanvas";
import type { Point } from "@/components/canvas/geometry";

export const Route = createFileRoute("/session/$sessionId")({
  head: () => ({
    meta: [
      { title: "Live design board — Loopboard" },
      {
        name: "description",
        content:
          "Shared system design canvas with component palette, connectors, freehand pen and live cursors.",
      },
      { property: "og:title", content: "Live design board — Loopboard" },
      { property: "og:description", content: "Shared system design canvas for live interviews." },
    ],
  }),
  component: SessionPage,
});

function SessionPage() {
  const { sessionId } = Route.useParams();
  const navigate = useNavigate();

  const [me, setMe] = useState<JoinedParticipant | null>(null);
  const [session, setSession] = useState<Session | null | "loading">("loading");
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [cursors, setCursors] = useState<CursorState[]>([]);
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [copied, setCopied] = useState(false);

  const lastSaved = useRef("");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // identity gate
  useEffect(() => {
    const identity = loadIdentity(sessionId);
    if (!identity) {
      void navigate({ to: "/join/$sessionId", params: { sessionId }, replace: true });
      return;
    }
    setMe(identity);
  }, [sessionId, navigate]);

  /**
   * Our participant token stops working if the host removes us, or if the
   * in-memory backend restarts. Either way the cure is the same: forget the
   * identity and go back through the join screen.
   */
  const handleFailure = useCallback(
    (cause: unknown) => {
      if (isUnauthorized(cause)) {
        clearIdentity(sessionId);
        void navigate({ to: "/join/$sessionId", params: { sessionId }, replace: true });
        return;
      }
      console.error(cause);
    },
    [sessionId, navigate],
  );

  const refreshSession = useCallback(async () => {
    try {
      setSession(await getSession(sessionId));
    } catch (cause) {
      handleFailure(cause);
    }
  }, [sessionId, handleFailure]);

  const refreshPresence = useCallback(async () => {
    try {
      const [ps, cs] = await Promise.all([listParticipants(sessionId), listCursors(sessionId)]);
      setParticipants(ps);
      setCursors(cs);
    } catch (cause) {
      handleFailure(cause);
    }
  }, [sessionId, handleFailure]);

  const refreshDoc = useCallback(async () => {
    try {
      const doc = await getCanvas(sessionId);
      const serialized = JSON.stringify(doc.nodes);
      if (serialized === lastSaved.current) return;
      lastSaved.current = serialized;
      setNodes(doc.nodes);
    } catch (cause) {
      handleFailure(cause);
    }
  }, [sessionId, handleFailure]);

  useEffect(() => {
    if (!me) return;
    void refreshSession();
    void refreshDoc();
    void refreshPresence();

    // Server-Sent Events carry no state: each notification is a cue to re-fetch.
    const unsub = subscribeToSession(sessionId, (kind) => {
      if (kind === "doc") void refreshDoc();
      if (kind === "presence") void refreshPresence();
      if (kind === "session") void refreshSession();
    });
    const beat = setInterval(() => {
      void heartbeat(sessionId, me.id).catch(handleFailure);
      void refreshPresence();
    }, 4000);

    // `beforeunload` cancels a fetch, so this one goes out as a beacon.
    const onLeave = () => leaveSessionOnUnload(sessionId, me.id);
    window.addEventListener("beforeunload", onLeave);
    return () => {
      unsub();
      clearInterval(beat);
      window.removeEventListener("beforeunload", onLeave);
    };
  }, [me, sessionId, refreshSession, refreshDoc, refreshPresence, handleFailure]);

  const handleChange = useCallback(
    (next: CanvasNode[]) => {
      setNodes(next);
      const serialized = JSON.stringify(next);
      lastSaved.current = serialized;
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        void saveCanvas(sessionId, { nodes: next }).catch((cause) => {
          // The server is the authority on who may write: if it refused, pull
          // its version back so the board stops showing an edit that never landed.
          if (isWriteRejected(cause)) {
            lastSaved.current = "";
            void refreshSession();
            void refreshDoc();
            return;
          }
          handleFailure(cause);
        });
      }, 120);
    },
    [sessionId, refreshDoc, refreshSession, handleFailure],
  );

  const cursorThrottle = useRef(0);
  const handleCursor = useCallback(
    (p: Point) => {
      if (!me) return;
      const now = Date.now();
      if (now - cursorThrottle.current < 90) return;
      cursorThrottle.current = now;
      void publishCursor(sessionId, {
        participantId: me.id,
        name: me.name,
        color: me.color,
        x: p.x,
        y: p.y,
        at: now,
      }).catch(() => {
        /* a dropped cursor frame is replaced by the next one */
      });
    },
    [me, sessionId],
  );

  if (session === "loading" || !me) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Joining the board…
      </main>
    );
  }
  if (session === null) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-3">
        <h1 className="text-xl font-semibold">Session not found</h1>
        <Link to="/" className="btn-base btn-primary">
          Back to dashboard
        </Link>
      </main>
    );
  }

  const isHost = me.role === "interviewer";
  const locked = session.status === "ended" || me.role === "observer" || session.canvasLocked;
  const others = cursors.filter((c) => c.participantId !== me.id);
  const joinUrl = typeof window === "undefined" ? "" : `${window.location.origin}/join/${sessionId}`;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-2.5">
        <Link to="/" className="flex items-center gap-2 text-sm font-semibold">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Layers className="h-4 w-4" />
          </span>
          Loopboard
        </Link>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{session.title}</p>
          <p className="flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground">
            <Radio className={`h-3 w-3 ${session.status === "live" ? "text-primary" : ""}`} />
            {session.status === "live" ? "live" : "ended"} · you are {me.name} ({me.role})
          </p>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-1">
            {participants.map((p) => (
              <span key={p.id} className="group flex items-center gap-1 text-xs" title={`${p.name} · ${p.role}`}>
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} />
                <span className="max-w-24 truncate">{p.name}</span>
                {isHost && p.id !== me.id && (
                  <button
                    type="button"
                    title={`Remove ${p.name}`}
                    onClick={() => void removeParticipant(sessionId, p.id).catch(handleFailure)}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <UserMinus className="h-3 w-3" />
                  </button>
                )}
              </span>
            ))}
            {participants.length === 0 && <span className="text-xs text-muted-foreground">no one here yet</span>}
          </div>

          <button
            type="button"
            className="btn-base btn-ghost"
            onClick={() => {
              void navigator.clipboard?.writeText(joinUrl);
              setCopied(true);
              setTimeout(() => setCopied(false), 1600);
            }}
          >
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied" : "Copy join link"}
          </button>

          {isHost &&
            (session.status === "live" ? (
              <button
                type="button"
                className="btn-base btn-danger"
                onClick={async () => {
                  if (!window.confirm("End the session? The board becomes read-only for everyone.")) return;
                  await endSession(sessionId).then(setSession).catch(handleFailure);
                }}
              >
                <Square className="h-4 w-4" />
                End session
              </button>
            ) : (
              <button
                type="button"
                className="btn-base btn-ghost"
                onClick={async () => {
                  await reopenSession(sessionId).then(setSession).catch(handleFailure);
                }}
              >
                Reopen
              </button>
            ))}

          <button
            type="button"
            className="btn-base btn-ghost"
            title="Leave session"
            onClick={async () => {
              await leaveSession(sessionId, me.id).catch(() => {});
              clearIdentity(sessionId);
              void navigate({ to: "/" });
            }}
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        <InterviewCanvas
          nodes={nodes}
          locked={locked}
          authorId={me.id}
          canClear={isHost && !locked}
          cursors={others}
          onChange={handleChange}
          onCursor={handleCursor}
        />
      </div>
    </div>
  );
}
