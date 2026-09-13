# Roadmap — System Design Interview Platform

## MVP tasks
- [x] ~~Mock API layer~~ → real backend client (`src/lib/api.ts`) against the FastAPI
      backend in `backend/`: bearer tokens, Server-Sent Events, interviewer sign-in
- [x] Design system in `src/styles.css`
- [x] Host dashboard `/` — create session, copy join link, list past sessions
- [x] Join screen `/join/$sessionId` — display name entry
- [x] Session canvas `/session/$sessionId` — palette, shapes, arrows, freehand, text, select, pan/zoom, undo, clear, end session
- [x] Presence bar with simulated remote participants + cursors

## Open (needs user input)
- [x] Real backend implementation — see `backend/README.md`
- Answers to spec open questions: identity verification, built-in video, view-only toggle, retention, stack constraints
