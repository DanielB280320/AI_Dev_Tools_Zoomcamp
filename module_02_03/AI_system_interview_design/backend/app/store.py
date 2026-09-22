"""The store: every read and write the API makes, as one method each.

The routers see the same surface they always did — `create_session`, `join`,
`get_doc` — so the database lives entirely behind this module, and behind
`app/db.py` for the connection itself. What changed with the move off a dict
is the contract on the records that come back: they are detached snapshots,
so changing one changes nothing until it is passed to a method here.

Each call is a single short transaction. That is the right unit for this API —
every operation is one HTTP request's worth of work — and it means no caller
ever has to think about when a change is committed.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .db import init_db, serialized_write, session_scope, upsert
from .models import CanvasNode, CursorState, Role, SessionStatus
from .tables import (
    Account,
    Base,
    CanvasNodeRow,
    CursorRow,
    ParticipantRecord,
    SessionRecord,
    TokenRecord,
    dump_node,
)

__all__ = [
    "DEFAULT_HOST_NAME",
    "DEFAULT_PARTICIPANT_NAME",
    "DEFAULT_TITLE",
    "PALETTE",
    "Account",
    "ParticipantRecord",
    "SessionRecord",
    "Store",
    "TokenRecord",
    "now_ms",
    "store",
]

# Ambiguity-free alphabet, same as the frontend mock's `randomId`.
ID_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"

# Participant colours, cycled by join order. Fixed by the contract.
PALETTE = (
    "#37d6c3",
    "#f5b83d",
    "#7dd3fc",
    "#fb7185",
    "#a3e635",
    "#e879f9",
    "#fb923c",
)

DEFAULT_TITLE = "Untitled interview"
DEFAULT_HOST_NAME = "Interviewer"
DEFAULT_PARTICIPANT_NAME = "Guest"


def now_ms() -> int:
    """Epoch milliseconds — the only time unit on the wire."""
    return int(time.time() * 1000)


def random_id(length: int = 12) -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(length))


def new_session_id() -> str:
    return random_id(16)


def new_participant_id() -> str:
    return f"p_{random_id(10)}"


def new_account_id() -> str:
    return f"acct_{random_id(10)}"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def clean(value: str, fallback: str) -> str:
    return value.strip() or fallback


def _next_seq(db: DbSession, column: Any, *where: Any) -> int:
    """The next value of a per-row ordering column.

    An integer the application picks, rather than an autoincrement one, because
    `seq` is not a key: two of these tables want it scoped to a session, and
    portable autoincrement only exists on a primary key.
    """
    highest = db.scalar(sa.select(sa.func.coalesce(sa.func.max(column), 0)).where(*where))
    return int(highest or 0) + 1


def _by_id(nodes: list[CanvasNode]) -> list[CanvasNode]:
    """Collapse repeated ids, keeping the first position and the last content.

    A document is a set of nodes keyed by id — that is what `PATCH /canvas/nodes`
    means by "merge by id", and what the node primary key enforces. A client
    that sends the same id twice in one `PUT` gets the same resolution the
    merge path would give it, not a 500.
    """
    positions: dict[str, int] = {}
    unique: list[CanvasNode] = []
    for node in nodes:
        position = positions.get(node.id)
        if position is None:
            positions[node.id] = len(unique)
            unique.append(node)
        else:
            unique[position] = node
    return unique


class Store:
    """Database-backed storage. One instance, shared; it holds no state itself."""

    def reset(self) -> None:
        """Empty every table. For tests — the server never calls this."""
        init_db()
        with session_scope() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(sa.delete(table))

    # ------------------------------- accounts -------------------------------

    def create_account(self, email: str, name: str, password_hash: str) -> Account:
        account = Account(
            id=new_account_id(),
            email=email.strip().lower(),
            name=clean(name, DEFAULT_HOST_NAME),
            password_hash=password_hash,
        )
        with session_scope() as db:
            db.add(account)
        return account

    def get_account(self, account_id: str | None) -> Account | None:
        if not account_id:
            return None
        with session_scope() as db:
            return db.get(Account, account_id)

    def account_by_email(self, email: str) -> Account | None:
        with session_scope() as db:
            return db.scalar(sa.select(Account).where(Account.email == email.strip().lower()))

    # -------------------------------- tokens --------------------------------

    def issue_interviewer_token(self, account_id: str) -> str:
        return self._issue(
            TokenRecord(token=new_token(), kind="interviewer", account_id=account_id)
        )

    def issue_participant_token(self, session_id: str, participant_id: str, role: Role) -> str:
        return self._issue(
            TokenRecord(
                token=new_token(),
                kind="participant",
                session_id=session_id,
                participant_id=participant_id,
                role=role,
            )
        )

    def _issue(self, record: TokenRecord) -> str:
        with session_scope() as db:
            db.add(record)
        return record.token

    def token(self, raw: str) -> TokenRecord | None:
        with session_scope() as db:
            return db.get(TokenRecord, raw)

    def revoke_token(self, raw: str) -> None:
        with session_scope() as db:
            db.execute(sa.delete(TokenRecord).where(TokenRecord.token == raw))

    def revoke_session_tokens(self, session_id: str) -> None:
        with session_scope() as db:
            db.execute(sa.delete(TokenRecord).where(TokenRecord.session_id == session_id))

    # ------------------------------- sessions -------------------------------

    def create_session(
        self,
        owner_id: str,
        title: str,
        host_name: str,
        *,
        session_id: str | None = None,
        created_at: int | None = None,
    ) -> SessionRecord:
        """`session_id` / `created_at` are only passed by the seeder."""
        record = SessionRecord(
            id=session_id or new_session_id(),
            owner_id=owner_id,
            title=clean(title, DEFAULT_TITLE),
            host_name=clean(host_name, DEFAULT_HOST_NAME),
            status=SessionStatus.live,
            created_at=created_at if created_at is not None else now_ms(),
            ended_at=None,
            canvas_locked=False,
        )
        with session_scope() as db:
            record.seq = _next_seq(db, SessionRecord.seq)
            db.add(record)
        return record

    def get_session(self, session_id: str) -> SessionRecord | None:
        with session_scope() as db:
            return db.get(SessionRecord, session_id)

    def list_sessions(self, owner_id: str) -> list[SessionRecord]:
        """The owner's sessions, newest first — the dashboard does not re-sort."""
        with session_scope() as db:
            return list(
                db.scalars(
                    sa.select(SessionRecord)
                    .where(SessionRecord.owner_id == owner_id)
                    .order_by(SessionRecord.created_at.desc(), SessionRecord.seq.desc())
                )
            )

    def session_count(self) -> int:
        with session_scope() as db:
            return db.scalar(sa.select(sa.func.count()).select_from(SessionRecord)) or 0

    def end_session(self, record: SessionRecord, *, ended_at: int | None = None) -> SessionRecord:
        """`ended_at` is only passed by the seeder, to backdate a finished board."""
        return self._patch_session(
            record,
            status=SessionStatus.ended,
            ended_at=ended_at if ended_at is not None else now_ms(),
            canvas_locked=True,
        )

    def reopen_session(self, record: SessionRecord) -> SessionRecord:
        return self._patch_session(
            record, status=SessionStatus.live, ended_at=None, canvas_locked=False
        )

    def _patch_session(self, record: SessionRecord, **fields: Any) -> SessionRecord:
        """Apply `fields` to the stored row and hand back the row as it stands.

        If the session was deleted in between, the caller's own snapshot is
        patched instead, so the response it is about to render stays coherent.
        """
        with session_scope() as db:
            target = db.get(SessionRecord, record.id) or record
            for name, value in fields.items():
                setattr(target, name, value)
            return target

    def delete_session(self, session_id: str) -> bool:
        """The session and everything hanging off it, in one transaction."""
        with session_scope() as db:
            record = db.get(SessionRecord, session_id)
            if record is None:
                return False
            for model in (CanvasNodeRow, CursorRow, ParticipantRecord, TokenRecord):
                db.execute(sa.delete(model).where(model.session_id == session_id))
            db.delete(record)
            return True

    def writes_blocked(self, record: SessionRecord) -> bool:
        return record.status is SessionStatus.ended or record.canvas_locked

    # ----------------------------- participants -----------------------------

    def join(self, session_id: str, name: str, role: Role) -> tuple[ParticipantRecord, str]:
        # Reads the roster, then writes a row based on what it counted — see
        # `serialized_write` for why that needs help on both dialects.
        with serialized_write(), session_scope() as db:
            self._lock_session(db, session_id)
            joined = self._roster_size(db, session_id)
            participant = ParticipantRecord(
                id=new_participant_id(),
                session_id=session_id,
                name=clean(name, DEFAULT_PARTICIPANT_NAME),
                role=role,
                color=PALETTE[joined % len(PALETTE)],
                last_seen=now_ms(),
                seq=_next_seq(
                    db, ParticipantRecord.seq, ParticipantRecord.session_id == session_id
                ),
            )
            db.add(participant)
        token = self.issue_participant_token(session_id, participant.id, role)
        return participant, token

    def list_participants(self, session_id: str) -> list[ParticipantRecord]:
        """The roster in join order, minus anyone whose heartbeat went quiet."""
        with session_scope() as db:
            if settings.prune_stale_participants:
                self._prune_stale(db, session_id)
            return list(
                db.scalars(
                    sa.select(ParticipantRecord)
                    .where(ParticipantRecord.session_id == session_id)
                    .order_by(ParticipantRecord.seq)
                )
            )

    def find_participant(self, session_id: str, participant_id: str) -> ParticipantRecord | None:
        with session_scope() as db:
            return self._participant(db, session_id, participant_id)

    def remove_participant(self, session_id: str, participant_id: str) -> bool:
        with session_scope() as db:
            participant = self._participant(db, session_id, participant_id)
            if participant is None:
                return False
            self._drop_cursors(db, session_id, [participant_id])
            db.delete(participant)
        # The token is left in place deliberately: `authorize_session` treats
        # roster membership as the authority, and keeping the token resolvable
        # is what lets a removed client's leave/heartbeat calls answer 204
        # instead of 401-looping.
        return True

    def touch_participant(
        self, session_id: str, participant_id: str, *, at: int | None = None
    ) -> bool:
        with session_scope() as db:
            participant = self._participant(db, session_id, participant_id)
            if participant is None:
                return False
            participant.last_seen = at if at is not None else now_ms()
            return True

    @staticmethod
    def _participant(
        db: DbSession, session_id: str, participant_id: str
    ) -> ParticipantRecord | None:
        return db.scalar(
            sa.select(ParticipantRecord).where(
                ParticipantRecord.session_id == session_id,
                ParticipantRecord.id == participant_id,
            )
        )

    @staticmethod
    def _lock_session(db: DbSession, session_id: str) -> None:
        """Make concurrent joins of one session queue behind each other.

        A join counts the roster to pick the next colour and the next `seq`,
        then inserts — so two people accepting the link at the same moment can
        both count the same roster and land on the same colour and the same
        position. Locking the session row first makes the second join wait for
        the first to commit, and it does so across processes, which is what a
        multi-worker deployment needs.

        `FOR UPDATE` is emitted on Postgres and silently dropped on SQLite,
        which has no such grammar; `serialized_write` is what covers SQLite.
        """
        db.execute(
            sa.select(SessionRecord.id).where(SessionRecord.id == session_id).with_for_update()
        )

    @staticmethod
    def _roster_size(db: DbSession, session_id: str) -> int:
        count = db.scalar(
            sa.select(sa.func.count())
            .select_from(ParticipantRecord)
            .where(ParticipantRecord.session_id == session_id)
        )
        return int(count or 0)

    def _prune_stale(self, db: DbSession, session_id: str) -> None:
        """Drop anyone who missed the heartbeat window, and their cursor with them."""
        cutoff = now_ms() - settings.participant_ttl_ms
        stale = sa.select(ParticipantRecord.id).where(
            ParticipantRecord.session_id == session_id,
            ParticipantRecord.last_seen <= cutoff,
        )
        db.execute(
            sa.delete(CursorRow).where(
                CursorRow.session_id == session_id,
                CursorRow.participant_id.in_(stale),
            )
        )
        db.execute(sa.delete(ParticipantRecord).where(ParticipantRecord.id.in_(stale)))

    @staticmethod
    def _drop_cursors(db: DbSession, session_id: str, participant_ids: list[str]) -> None:
        db.execute(
            sa.delete(CursorRow).where(
                CursorRow.session_id == session_id,
                CursorRow.participant_id.in_(participant_ids),
            )
        )

    # -------------------------------- cursors -------------------------------

    def put_cursor(self, session_id: str, cursor: CursorState) -> None:
        """Upsert by participant: a cursor keeps the place it first took in the
        list, so a moving pointer does not reshuffle everyone else's.

        One `INSERT … ON CONFLICT DO UPDATE`, rather than a read followed by an
        insert: this is the hottest write in the app (every participant
        publishes at roughly 11 Hz), and on Postgres two first publishes
        arriving together would both read no row and both insert. `seq` is only
        set by the insert, which is what pins the position.
        """
        with serialized_write(), session_scope() as db:
            seq = _next_seq(db, CursorRow.seq, CursorRow.session_id == session_id)
            upsert(
                db,
                CursorRow,
                CursorRow.columns_for(session_id, cursor, seq),
                update=CursorRow.MUTABLE,
            )

    def list_cursors(self, session_id: str) -> list[CursorState]:
        """Only cursors published within the TTL; the server owns the filtering."""
        cutoff = now_ms() - settings.cursor_ttl_ms
        with session_scope() as db:
            rows = db.scalars(
                sa.select(CursorRow)
                .where(CursorRow.session_id == session_id, CursorRow.at > cutoff)
                .order_by(CursorRow.seq)
            )
            return [row.to_model() for row in rows]

    def get_cursor(self, session_id: str, participant_id: str) -> CursorState | None:
        """The stored cursor, TTL ignored — what `list_cursors` filtered out."""
        with session_scope() as db:
            row = db.get(CursorRow, (session_id, participant_id))
            return row.to_model() if row is not None else None

    # --------------------------------- canvas -------------------------------

    def get_doc(self, session_id: str) -> list[CanvasNode]:
        """The whole board in z-order. An unknown session reads as an empty one."""
        with session_scope() as db:
            rows = db.scalars(
                sa.select(CanvasNodeRow)
                .where(CanvasNodeRow.session_id == session_id)
                .order_by(CanvasNodeRow.position)
            )
            return [row.to_model() for row in rows]

    def node_count(self, session_id: str) -> int:
        """How many nodes the board holds, without reading any of them."""
        with session_scope() as db:
            count = db.scalar(
                sa.select(sa.func.count())
                .select_from(CanvasNodeRow)
                .where(CanvasNodeRow.session_id == session_id)
            )
            return int(count or 0)

    def set_doc(self, session_id: str, nodes: list[CanvasNode]) -> None:
        """Whole-document replace: array order becomes `position`, verbatim."""
        with session_scope() as db:
            db.execute(sa.delete(CanvasNodeRow).where(CanvasNodeRow.session_id == session_id))
            db.flush()
            db.add_all(
                CanvasNodeRow.from_model(session_id, node, position)
                for position, node in enumerate(_by_id(nodes))
            )

    def upsert_nodes(self, session_id: str, nodes: list[CanvasNode]) -> None:
        """Merge by id: known ids are replaced in place, new ids appended.

        In-place replacement keeps z-order stable — `position` is the render
        order, so moving an edited node to the end would raise it above
        everything else.
        """
        with session_scope() as db:
            current = {
                row.node_id: row
                for row in db.scalars(
                    sa.select(CanvasNodeRow).where(CanvasNodeRow.session_id == session_id)
                )
            }
            top = max((row.position for row in current.values()), default=-1)
            for node in _by_id(nodes):
                row = current.get(node.id)
                if row is None:
                    top += 1
                    row = CanvasNodeRow.from_model(session_id, node, top)
                    current[node.id] = row
                    db.add(row)
                else:
                    row.data = dump_node(node)

    def delete_nodes(self, session_id: str, ids: list[str]) -> None:
        """Unknown ids are ignored; the gaps left in `position` are harmless."""
        if not ids:
            return
        with session_scope() as db:
            db.execute(
                sa.delete(CanvasNodeRow).where(
                    CanvasNodeRow.session_id == session_id,
                    CanvasNodeRow.node_id.in_(ids),
                )
            )


store = Store()
