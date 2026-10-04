"""Product metrics: what people do with Loopboard, rather than how the server is.

Three instruments, exported with the rest of the telemetry (`app/telemetry.py`)
and drawn by the "Loopboard" Grafana dashboard (`observability/grafana/`):

* `loopboard.sessions.created` — interview rooms created through the API. The
  demo seed writes through the store, not the API, so it never counts.
* `loopboard.participants.active` — people in a live room right now, by role.
  "Right now" is the presence rule the roster already uses: a heartbeat within
  `participant_ttl_ms`. A gauge read from the database on each collection,
  rather than an up/down counter kept in step with joins and leaves, because
  people mostly leave by closing the tab, and nothing would decrement for that.
* `loopboard.canvas.elements.created` — elements added to a board, by type
  (`shape`, `arrow`, `stroke`, `text`). Counted by id, so editing or moving an
  element — which re-sends it — is not a creation.

Until `setup_telemetry` binds them to its meter provider, the instruments are
no-ops, so the call sites never ask whether telemetry is on. Bound to that
provider explicitly rather than through the global one, because the global can
be set only once per process and the tests each build their own.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import get_args

import sqlalchemy as sa
from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

from .config import settings
from .db import session_scope
from .models import CanvasNode, Role, SessionStatus
from .store import now_ms
from .tables import ParticipantRecord, SessionRecord

#: The `type` discriminator of each member of the `CanvasNode` union.
ELEMENT_TYPES: tuple[str, ...] = tuple(
    member.model_fields["type"].default for member in get_args(get_args(CanvasNode)[0])
)


class _Instruments:
    def __init__(self, meter: metrics.Meter, *, observe: bool) -> None:
        self.sessions_created = meter.create_counter(
            "loopboard.sessions.created",
            unit="{session}",
            description="Interview rooms created",
        )
        self.elements_created = meter.create_counter(
            "loopboard.canvas.elements.created",
            unit="{element}",
            description="Elements added to a board, by element type",
        )
        if observe:
            # Every series starts at an explicit 0. Prometheus's `increase()`
            # needs a sample before the first increment to see it at all: a
            # series that first appears already at 1 reads as no change, so
            # the first room a process creates would never show on a graph.
            self.sessions_created.add(0)
            for kind in ELEMENT_TYPES:
                self.elements_created.add(0, {"element.type": kind})
            meter.create_observable_gauge(
                "loopboard.participants.active",
                callbacks=[_observe_active_participants],
                unit="{participant}",
                description="Participants with a current heartbeat in a live interview room, by role",
            )


_instruments = _Instruments(metrics.NoOpMeter("loopboard"), observe=False)


def bind(meter_provider: metrics.MeterProvider) -> None:
    """Report through `meter_provider` from now on. Called by `setup_telemetry`."""
    global _instruments
    _instruments = _Instruments(meter_provider.get_meter("loopboard"), observe=True)


def record_session_created() -> None:
    _instruments.sessions_created.add(1)


def record_elements_created(nodes: Iterable[CanvasNode]) -> None:
    for kind, count in Counter(node.type for node in nodes).items():
        _instruments.elements_created.add(count, {"element.type": kind})


def active_participants() -> dict[str, int]:
    """Participants with a current heartbeat in a live session, per role.

    Every role is present, at zero if need be, so a role whose last member left
    reads as 0 rather than as a series that stopped.
    """
    cutoff = now_ms() - settings.participant_ttl_ms
    with session_scope() as db:
        rows = db.execute(
            sa.select(ParticipantRecord.role, sa.func.count())
            .join(SessionRecord, SessionRecord.id == ParticipantRecord.session_id)
            .where(
                SessionRecord.status == SessionStatus.live,
                ParticipantRecord.last_seen > cutoff,
            )
            .group_by(ParticipantRecord.role)
        ).all()
    counts = {role.value: 0 for role in Role}
    counts.update({Role(role).value: int(count) for role, count in rows})
    return counts


def _observe_active_participants(_options: CallbackOptions) -> Iterable[Observation]:
    return [
        Observation(count, {"participant.role": role})
        for role, count in active_participants().items()
    ]
