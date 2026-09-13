"""The schema — one mapped class per table, no dialect-specific types.

These classes are also the records the rest of the app passes around: a query
returns them with every column loaded and `expire_on_commit` off, so they stay
readable after the transaction closes. Nothing here declares a relationship,
which is what makes that safe — a detached record can never trigger a lazy
load. Walking from a session to its participants is a `Store` method instead.

Types are deliberately plain (`String` with a length, `BigInteger`, `Double`,
`JSON`), and the enums are stored as their string values rather than a native
database enum, so the same metadata creates the same tables on SQLite and on
Postgres. `JSON` is the one place a dialect is named, and only to take the
better Postgres representation when it is available.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from . import models
from .models import CanvasNode, CursorState, Role, SessionStatus

#: Epoch milliseconds overflow a 32-bit INTEGER, so every timestamp is 64-bit.
Millis = sa.BigInteger


#: Enum columns hold the wire value ("interviewer", "ended"), not the Python
#: member name, and are VARCHAR everywhere — a native Postgres ENUM would need
#: a migration to gain a value.
def _enum(enum_type: type, name: str) -> sa.Enum:
    return sa.Enum(
        enum_type,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )


#: Postgres stores JSONB far more usefully than JSON; everything else gets the
#: generic type, which is TEXT plus (de)serialisation on SQLite.
NodeJson = sa.JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class Account(Base):
    """A signed-in interviewer. `password_hash` never leaves this process."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    email: Mapped[str] = mapped_column(sa.String(200), unique=True)
    name: Mapped[str] = mapped_column(sa.String(100))
    password_hash: Mapped[str] = mapped_column(sa.String(255))


class TokenRecord(Base):
    """An issued bearer token. Opaque to clients; the scope lives here.

    No foreign keys: a participant token deliberately outlives the participant
    row, which is what lets a removed client's leave/heartbeat calls answer 204
    instead of 401-looping.
    """

    __tablename__ = "tokens"

    token: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(16))
    account_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    participant_id: Mapped[str | None] = mapped_column(sa.String(64))
    role: Mapped[Role | None] = mapped_column(_enum(Role, "role"))


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    host_name: Mapped[str] = mapped_column(sa.String(100))
    status: Mapped[SessionStatus] = mapped_column(
        _enum(SessionStatus, "session_status"), default=SessionStatus.live
    )
    created_at: Mapped[int] = mapped_column(Millis, index=True)
    ended_at: Mapped[int | None] = mapped_column(Millis, default=None)
    canvas_locked: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    #: Creation order, to break `created_at` ties: two sessions created inside
    #: the same millisecond still have to list newest first.
    seq: Mapped[int] = mapped_column(sa.Integer, default=0)

    def to_model(self) -> models.Session:
        return models.Session(
            id=self.id,
            title=self.title,
            hostName=self.host_name,
            status=self.status,
            createdAt=self.created_at,
            endedAt=self.ended_at,
            canvasLocked=self.canvas_locked,
        )


class ParticipantRecord(Base):
    """One membership. `seq` is join order, which picks the colour and the
    order the presence bar renders."""

    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        sa.String(64), sa.ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(100))
    role: Mapped[Role] = mapped_column(_enum(Role, "role"))
    color: Mapped[str] = mapped_column(sa.String(7))
    last_seen: Mapped[int] = mapped_column(Millis)
    seq: Mapped[int] = mapped_column(sa.Integer, default=0)

    def to_model(self) -> models.Participant:
        return models.Participant(
            id=self.id,
            name=self.name,
            role=self.role,
            color=self.color,
            lastSeen=self.last_seen,
        )


class CursorRow(Base):
    """The latest position published by one participant. One row per cursor —
    a publish is an upsert, and `at` is what `GET /cursors` filters on."""

    __tablename__ = "cursors"

    session_id: Mapped[str] = mapped_column(
        sa.String(64), sa.ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    participant_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(100))
    color: Mapped[str] = mapped_column(sa.String(7))
    x: Mapped[float] = mapped_column(sa.Double)
    y: Mapped[float] = mapped_column(sa.Double)
    at: Mapped[int] = mapped_column(Millis)
    #: First-publish order, so the list stays stable as cursors are updated.
    seq: Mapped[int] = mapped_column(sa.Integer, default=0)

    @classmethod
    def from_model(cls, session_id: str, cursor: CursorState, seq: int) -> CursorRow:
        row = cls(session_id=session_id, participant_id=cursor.participantId, seq=seq)
        row.apply(cursor)
        return row

    def apply(self, cursor: CursorState) -> None:
        self.name = cursor.name
        self.color = cursor.color
        self.x = cursor.x
        self.y = cursor.y
        self.at = cursor.at

    def to_model(self) -> CursorState:
        return CursorState(
            participantId=self.participant_id,
            name=self.name,
            color=self.color,
            x=self.x,
            y=self.y,
            at=self.at,
        )


class CanvasNodeRow(Base):
    """One node of one board.

    The node itself is kept as JSON — the four node types share almost no
    fields, and only the server's own validation ever looks inside. What the
    database does own is identity and order: `position` is z-order, which the
    contract says is array order.
    """

    __tablename__ = "canvas_nodes"

    session_id: Mapped[str] = mapped_column(
        sa.String(64), sa.ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    position: Mapped[int] = mapped_column(sa.Integer, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(NodeJson)

    @classmethod
    def from_model(cls, session_id: str, node: CanvasNode, position: int) -> CanvasNodeRow:
        return cls(
            session_id=session_id,
            node_id=node.id,
            position=position,
            data=dump_node(node),
        )

    def to_model(self) -> CanvasNode:
        return models.CanvasNodeAdapter.validate_python(self.data)


def dump_node(node: CanvasNode) -> dict[str, Any]:
    """`by_alias` keeps `ArrowNode.from_` on the wire spelling, `from`."""
    return node.model_dump(by_alias=True, mode="json")
