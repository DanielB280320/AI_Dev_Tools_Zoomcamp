# System Design Interview Platform — Specification

## 1. Overview

A web-based tool for conducting live system design interviews. The interviewer creates a
session and shares a link. The interviewer and one or more candidates join a **shared,
real-time collaborative canvas** where they can:

- Drag and drop predefined "component" shapes (Database, Queue, Service, LLM, Cache,
  Load Balancer, Client, API Gateway, etc.)
- Connect components with directional arrows
- Freehand-draw on the canvas (for annotations, quick sketches, circling things)
- See each other's cursors and edits live, with no manual refresh

This document assumes an MVP scope suitable for a first build, with clearly separated
"Phase 2" items so the initial build stays lean. Assumptions I made where your description
was open-ended are called out explicitly — flag any you want changed.

---

## 2. Roles & Access

| Role | How they join | Permissions |
|---|---|---|
| **Interviewer (host)** | Signs in (or creates a session from an authenticated dashboard) | Creates sessions, generates join links, full edit rights, can lock canvas, can remove participants, can end/reset session |
| **Candidate (guest)** | Opens the join link, enters a display name — no account needed | Full edit rights on canvas by default (matches your "candidate can edit" requirement) |
| **Observer** *(Phase 2)* | Opens a separate "view-only" link | Read-only, sees live updates, cannot edit |

**Assumption:** Candidates join anonymously via link + display name, no signup. If you need
identity verification (e.g. tied to an ATS candidate record), that changes the join flow —
flag it and I'll adjust.

**Assumption:** Any participant (interviewer or candidate) can edit anything by default —
i.e. it's a shared whiteboard, not a turn-based or locked system. If you want the
interviewer to be able to toggle a candidate to "view only" mid-session, that's a small
Phase 2 addition (per-user permission flags).

---

## 3. Session Lifecycle

1. Interviewer clicks **"New Interview Session"** → system creates a session with a unique
   ID and a fresh empty canvas.
2. Interviewer gets a shareable link: `https://app.example.com/session/{sessionId}`
3. Interviewer shares the link with the candidate(s) (email, Slack, whatever — outside this
   system's scope).
4. Each person who opens the link enters a display name (or is auto-identified if they're
   logged in) and joins the same canvas room.
5. All participants see each other's changes in real time (cursors, shape adds/edits/moves,
   arrows, freehand strokes).
6. Interviewer can **end the session**, which freezes the canvas (read-only) and stores a
   permanent snapshot for later review/scoring.
7. Sessions persist so the interviewer can revisit the final board afterward (for scoring,
   sharing with a hiring committee, etc.).

**Multiple simultaneous sessions:** Each session is fully isolated — the platform supports
many concurrent sessions running at once (many interviews happening at the same time across
different interviewers), each with its own room/canvas.

**Multiple people in one session:** Explicitly supported — more than one candidate or
observer can be in the same room (e.g. panel interviews), all seeing the same live canvas.

---

## 4. Canvas Functional Requirements

### 4.1 Component shapes (drag-and-drop palette)

A sidebar palette of predefined system-design building blocks. Each is a labeled shape
(rectangle/cylinder/etc.) that can be dropped onto the canvas, resized, relabeled, and
recolored.

Suggested default component set:

- **Client / User**
- **Load Balancer**
- **API Gateway**
- **Service** (generic rectangle — candidate renames it, e.g. "Auth Service")
- **Database** (SQL — cylinder shape)
- **NoSQL Store** (distinct shape/icon)
- **Cache** (e.g. Redis)
- **Queue / Message Broker** (e.g. Kafka, SQS)
- **LLM / AI Service** (your specific ask — a distinct rectangle type, e.g. "LLM Call")
- **CDN**
- **Object Storage / Blob Store**
- **Generic Box** (freely labeled, blank rectangle for anything not covered)

Each shape instance supports:
- Editable text label
- Move / resize / rotate
- Delete
- Duplicate
- Color/style variants *(Phase 2 — nice-to-have, not core)*

**Assumption:** the component palette is a fixed, curated set (not user-uploadable icons)
for the MVP. Custom/uploaded icons would be Phase 2.

### 4.2 Connectors (arrows)

- Draw an arrow by dragging from one shape's edge to another shape's edge.
- Arrows stay attached ("magnetically") if either shape is moved.
- Arrows can be labeled (e.g. "writes to", "async", "1:N").
- Arrow style options: solid vs dashed (e.g. sync vs async call), direction (one-way,
  bidirectional).
- Arrows can also connect to a free point on the canvas (not just shape-to-shape), for
  flexibility.

### 4.3 Freehand drawing

- A pen/marker tool for freeform strokes, independent of the shape system — for circling,
  underlining, writing notes, sketching things the component palette doesn't cover.
- Adjustable stroke color and thickness.
- Eraser tool for freehand strokes.
- Freehand strokes and shapes coexist on the same canvas layer/z-order, both fully
  real-time-synced.

### 4.4 General canvas tools

- Text tool (standalone text, not attached to a shape) — for labels/notes.
- Select / multi-select (drag a box to select multiple elements, move/delete together).
- Pan and zoom (infinite or large bounded canvas).
- Undo/redo — **note:** in a multi-user real-time canvas, undo/redo needs to be scoped
  carefully (usually "undo my last action," not a global undo that could yank away someone
  else's edit). I'd recommend per-user undo stacks.
- Clear canvas (interviewer-only permission, with a confirmation prompt).

---

## 5. Real-Time Collaboration Requirements

This is the technical core of the system, so it's worth being precise:

- **Live sync:** every participant sees shape moves, additions, deletions, arrow changes,
  and pen strokes within roughly 100–200ms of the change happening (typical for this class
  of app).
- **Live cursors:** each participant's cursor position and name label are visible to
  everyone else, in real time (this is what makes it feel "alive").
- **Presence:** a list of who's currently in the session (name + a colored dot).
- **Conflict handling:** if two people edit at once (e.g. both drag the same box), the
  system needs deterministic conflict resolution rather than corrupting state. The
  standard approach is a **CRDT** (Conflict-free Replicated Data Type) for the canvas
  document — this avoids manual merge logic entirely and is the accepted best practice for
  this exact category of app (Figma, tldraw, and Excalidraw's multiplayer mode all use this
  approach).
- **Reconnection:** if a participant's network drops, they should be able to rejoin and
  resync to current state automatically.
- **Late joiners:** anyone joining mid-session immediately receives the full current canvas
  state, not just future changes.

---

## 6. Suggested Architecture

*(This is a recommendation, not a hard requirement — flag if you have constraints, e.g. a
mandated cloud provider or existing frontend stack.)*

| Layer | Recommendation | Why |
|---|---|---|
| Canvas rendering | **tldraw SDK** (or Excalidraw) as the base, extended with a custom shape palette for "Database", "LLM", etc. | Both are open-source, already solve infinite canvas + shapes + freehand drawing + real-time sync out of the box, and are built to be extended with custom shape types rather than built from scratch. Building this canvas layer from zero is by far the most expensive part of the project. |
| Real-time sync | **Yjs** (CRDT) over WebSockets, or tldraw's built-in sync server | Handles multi-user conflict resolution automatically |
| Backend / session management | Node.js (or your existing backend stack) — issues session IDs, join links, stores snapshots | Lightweight; the CRDT server handles the heavy real-time lifting |
| Persistence | Postgres (session metadata, users) + object storage or a document store for canvas snapshots | Canvas state itself can be stored as the serialized CRDT doc |
| Auth | Interviewer: standard email/password or SSO. Candidate: linked session token, no account | Matches the access model in §2 |
| Deployment | Any standard containerized deploy (your existing infra) | No special requirements beyond WebSocket support |

**Why not build the canvas from scratch:** rendering, hit-testing, shape connectors, pan/zoom,
and CRDT-backed multiplayer sync are each substantial projects on their own. Starting from an
existing open-source whiteboard engine and adding your specific component palette on top is
dramatically faster and lower-risk than a fully custom canvas.

---

## 7. Non-Functional Requirements

- **Concurrency:** support many simultaneous independent sessions (each isolated), plus
  multiple participants per session (design for at least 5–10 concurrent users per session
  without degradation, even though most interviews will be 2 people).
- **Latency:** sub-200ms propagation of edits under normal network conditions.
- **Data retention:** session canvases persist after the interview ends (for review/scoring)
  — define a retention period (e.g. 90 days) — flag if you have a specific requirement here.
- **Security:** session links should be unguessable (long random IDs), and ideally
  expirable/single-use-ish if you want to prevent a link being reused for a different
  candidate.
- **Browser support:** modern evergreen browsers (Chrome, Edge, Firefox, Safari); no IE.

---

## 8. Explicitly Out of Scope for MVP (Phase 2+ ideas)

- Video/audio calling (likely you'll run this alongside Zoom/Meet rather than build it in —
  confirm if you actually want built-in video)
- Session recording/playback (replaying the canvas edit-by-edit over time)
- Scoring rubrics / structured interviewer notes tied to canvas elements
- Custom/uploaded icons beyond the curated component palette
- Per-user granular permissions (view-only toggle mid-session)
- Templates (pre-built starting canvases for common interview questions, e.g. "design
  Twitter")
- Export canvas to PNG/PDF/Markdown summary

---

## 9. Open Questions for You

1. Do candidates need to be identity-verified, or is "click link, type name" sufficient?
2. Do you want built-in video/audio, or will interviews run alongside a separate call (Zoom,
   Meet, etc.)?
3. Should the interviewer be able to restrict a candidate to view-only at any point, or is
   full shared editing always fine?
4. How long should past session canvases be retained, and who can view them afterward
   (just the interviewer, or a hiring team)?
5. Any constraint on tech stack (existing frontend framework, cloud provider, or
   infra you need this to fit into)?

---

*Prepared as a starting specification — happy to expand any section (e.g. detailed data
model / API design, or a wireframe of the canvas UI) once you've confirmed the open
questions above.*
