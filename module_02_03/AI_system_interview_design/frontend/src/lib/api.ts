/**
 * REAL BACKEND CLIENT
 * -----------------------------------------------------------------------------
 * Replaces the old localStorage/BroadcastChannel mock. One function per
 * operation in the backend's OpenAPI contract (../../openapi.yaml), with the
 * same names and payload shapes the UI already used.
 *
 * Credentials are ambient rather than threaded through every call site:
 *   - session-scoped calls read the participant token stored for that session
 *     by `identity.ts` (written at join time),
 *   - dashboard calls read the signed-in interviewer's token.
 *
 * Realtime is Server-Sent Events: `subscribeToSession` keeps the same
 * "re-fetch on notification" contract the BroadcastChannel version had.
 */
import type { CanvasDoc, CanvasNode } from "./canvas-types";
import { loadAuth, loadIdentity } from "./identity";

export type Role = "interviewer" | "candidate" | "observer";
export type SessionStatus = "live" | "ended";

export interface Participant {
  id: string;
  name: string;
  role: Role;
  color: string;
  lastSeen: number;
}

/** A participant plus the bearer token that authenticates it in this session. */
export interface JoinedParticipant extends Participant {
  token: string;
}

export interface Session {
  id: string;
  title: string;
  hostName: string;
  status: SessionStatus;
  createdAt: number;
  endedAt: number | null;
  canvasLocked: boolean;
}

export interface CursorState {
  participantId: string;
  name: string;
  color: string;
  x: number;
  y: number;
  at: number;
}

export interface Interviewer {
  id: string;
  email: string;
  name: string;
}

export interface AuthSession {
  token: string;
  interviewer: Interviewer;
}

/** Set `VITE_API_URL` to point at a backend other than the local one. */
const env = (import.meta as { env?: Record<string, string | undefined> }).env ?? {};

export const API_URL = (env["VITE_API_URL"] ?? "http://localhost:8000").replace(/\/$/, "");

/* --------------------------------- errors -------------------------------- */

/** A non-2xx response. `code` is the backend's stable machine-readable code. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const isUnauthorized = (error: unknown) => error instanceof ApiError && error.status === 401;

/** True when the board is frozen (ended or locked) or the caller is an observer. */
export const isWriteRejected = (error: unknown) =>
  error instanceof ApiError && (error.status === 409 || error.status === 403);

/* -------------------------------- requests ------------------------------- */

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Bearer token. `null` sends the request unauthenticated. */
  token?: string | null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const init: RequestInit = { method, headers };
  if (body !== undefined) init.body = JSON.stringify(body);

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "network_error", `Could not reach the API at ${API_URL}.`);
  }

  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload ?? {}) as { error?: string; message?: string };
    throw new ApiError(
      response.status,
      error.error ?? "error",
      error.message ?? `${method} ${path} failed with ${response.status}.`,
    );
  }
  return payload as T;
}

/** The token for a session, from the identity saved when we joined it. */
function sessionToken(sessionId: string): string | null {
  return loadIdentity(sessionId)?.token ?? null;
}

/** The signed-in interviewer's token, for the account-scoped endpoints. */
function accountToken(): string | null {
  return loadAuth()?.token ?? null;
}

/* ----------------------------- interviewer auth --------------------------- */

export function signIn(input: { email: string; password: string }): Promise<AuthSession> {
  return request<AuthSession>("/auth/login", { method: "POST", body: input, token: null });
}

export function register(input: {
  email: string;
  password: string;
  name: string;
}): Promise<AuthSession> {
  return request<AuthSession>("/auth/register", { method: "POST", body: input, token: null });
}

export function signOut(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST", token: accountToken() });
}

/* --------------------------------- ids ----------------------------------- */

export { newNodeId } from "./canvas-types";

/* ------------------------------- sessions -------------------------------- */

export function createSession(input: { title: string; hostName: string }): Promise<Session> {
  return request<Session>("/sessions", { method: "POST", body: input, token: accountToken() });
}

export function listSessions(): Promise<Session[]> {
  return request<Session[]>("/sessions", { token: accountToken() });
}

/** Public — the join page calls this before any identity exists. `null` on 404. */
export async function getSession(sessionId: string): Promise<Session | null> {
  try {
    return await request<Session>(`/sessions/${sessionId}`, { token: null });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function endSession(sessionId: string): Promise<Session> {
  return request<Session>(`/sessions/${sessionId}/end`, {
    method: "POST",
    token: sessionToken(sessionId) ?? accountToken(),
  });
}

export function reopenSession(sessionId: string): Promise<Session> {
  return request<Session>(`/sessions/${sessionId}/reopen`, {
    method: "POST",
    token: sessionToken(sessionId) ?? accountToken(),
  });
}

export function deleteSession(sessionId: string): Promise<void> {
  return request<void>(`/sessions/${sessionId}`, { method: "DELETE", token: accountToken() });
}

/* ------------------------------ participants ----------------------------- */

/** Public. The response carries the token every other call in this session needs. */
export function joinSession(input: {
  sessionId: string;
  name: string;
  role: Role;
}): Promise<JoinedParticipant> {
  return request<JoinedParticipant>(`/sessions/${input.sessionId}/participants`, {
    method: "POST",
    body: { name: input.name, role: input.role },
    token: null,
  });
}

export function listParticipants(sessionId: string): Promise<Participant[]> {
  return request<Participant[]>(`/sessions/${sessionId}/participants`, {
    token: sessionToken(sessionId),
  });
}

export function leaveSession(sessionId: string, participantId: string): Promise<void> {
  return request<void>(`/sessions/${sessionId}/participants/${participantId}`, {
    method: "DELETE",
    token: sessionToken(sessionId),
  });
}

/**
 * Leave from a `beforeunload` handler. `sendBeacon` survives the page teardown
 * that would cancel a `fetch`, but it can only POST and cannot set headers, so
 * the token travels in the body. Falls back to a keepalive fetch.
 */
export function leaveSessionOnUnload(sessionId: string, participantId: string): void {
  const token = sessionToken(sessionId);
  if (!token) return;
  const url = `${API_URL}/sessions/${sessionId}/participants/${participantId}/leave`;
  const body = JSON.stringify({ token });
  if (typeof navigator !== "undefined" && navigator.sendBeacon) {
    navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
    return;
  }
  void fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {});
}

export const removeParticipant = leaveSession;

export function heartbeat(sessionId: string, participantId: string): Promise<void> {
  return request<void>(`/sessions/${sessionId}/participants/${participantId}/heartbeat`, {
    method: "POST",
    token: sessionToken(sessionId),
  });
}

/* -------------------------------- cursors -------------------------------- */

export function publishCursor(sessionId: string, cursor: CursorState): Promise<void> {
  return request<void>(`/sessions/${sessionId}/cursors/${cursor.participantId}`, {
    method: "PUT",
    body: cursor,
    token: sessionToken(sessionId),
  });
}

/** Only cursors published in the last 15 s — the server does that filtering. */
export function listCursors(sessionId: string): Promise<CursorState[]> {
  return request<CursorState[]>(`/sessions/${sessionId}/cursors`, {
    token: sessionToken(sessionId),
  });
}

/* --------------------------------- canvas -------------------------------- */

export function getCanvas(sessionId: string): Promise<CanvasDoc> {
  return request<CanvasDoc>(`/sessions/${sessionId}/canvas`, { token: sessionToken(sessionId) });
}

/** Whole-document, last-write-wins replace. Array order is z-order. */
export function saveCanvas(sessionId: string, doc: CanvasDoc): Promise<void> {
  return request<void>(`/sessions/${sessionId}/canvas`, {
    method: "PUT",
    body: doc,
    token: sessionToken(sessionId),
  });
}

export function upsertNodes(sessionId: string, nodes: CanvasNode[]): Promise<void> {
  return request<void>(`/sessions/${sessionId}/canvas/nodes`, {
    method: "PATCH",
    body: { nodes },
    token: sessionToken(sessionId),
  });
}

export function deleteNodes(sessionId: string, ids: string[]): Promise<void> {
  return request<void>(`/sessions/${sessionId}/canvas/nodes/delete`, {
    method: "POST",
    body: { ids },
    token: sessionToken(sessionId),
  });
}

/* ------------------------------- realtime -------------------------------- */

export type BusEventKind = "doc" | "presence" | "session";

/**
 * Subscribe to this session's change notifications. The events carry no state:
 * on each one the caller re-fetches what changed, exactly as with the old bus.
 *
 * `EventSource` cannot set an `Authorization` header, so the token goes in the
 * query string — the endpoint accepts both. Reconnection is the browser's job.
 */
export function subscribeToSession(
  sessionId: string,
  handler: (kind: BusEventKind) => void,
): () => void {
  if (typeof EventSource === "undefined") return () => {};
  const token = sessionToken(sessionId);
  if (!token) return () => {};

  const source = new EventSource(
    `${API_URL}/sessions/${sessionId}/events?token=${encodeURIComponent(token)}`,
  );
  const kinds: BusEventKind[] = ["doc", "presence", "session"];
  const listeners = kinds.map((kind) => {
    const listener = () => handler(kind);
    source.addEventListener(kind, listener);
    return [kind, listener] as const;
  });

  return () => {
    for (const [kind, listener] of listeners) source.removeEventListener(kind, listener);
    source.close();
  };
}
