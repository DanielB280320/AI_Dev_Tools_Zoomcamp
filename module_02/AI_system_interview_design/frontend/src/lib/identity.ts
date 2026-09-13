/**
 * Who the browser is, persisted in localStorage.
 *
 * Two kinds of credential, matching the backend's two bearer schemes:
 *   - one participant identity per session, written at join time, carrying the
 *     session-scoped token (`sdi.me.<sessionId>`),
 *   - one interviewer sign-in for the dashboard (`sdi.auth`).
 *
 * `api.ts` reads both from here, so call sites never pass tokens around.
 */
import type { AuthSession, JoinedParticipant } from "./api";

const key = (sessionId: string) => `sdi.me.${sessionId}`;

export function saveIdentity(sessionId: string, p: JoinedParticipant) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key(sessionId), JSON.stringify(p));
}

export function loadIdentity(sessionId: string): JoinedParticipant | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<JoinedParticipant>;
    // An identity without a token predates the real backend (or the session was
    // deleted server-side); treat it as absent so the join flow runs again.
    if (!parsed.id || !parsed.token) return null;
    return parsed as JoinedParticipant;
  } catch {
    return null;
  }
}

export function clearIdentity(sessionId: string) {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(key(sessionId));
}

const HOST_NAME = "sdi.hostName";

export function saveHostName(name: string) {
  if (typeof window !== "undefined") window.localStorage.setItem(HOST_NAME, name);
}
export function loadHostName(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(HOST_NAME) ?? "";
}

/* --------------------------- interviewer sign-in -------------------------- */

const AUTH = "sdi.auth";

export function saveAuth(auth: AuthSession) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH, JSON.stringify(auth));
}

export function loadAuth(): AuthSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AuthSession>;
    return parsed.token && parsed.interviewer ? (parsed as AuthSession) : null;
  } catch {
    return null;
  }
}

export function clearAuth() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH);
}
