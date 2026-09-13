"""The shared canvas document.

`PUT` is a last-write-wins whole-document replace — the MVP contract, and the
only write path the frontend uses today (120 ms debounce). The node-level
operations exist for the client module that is not yet wired to the UI, and are
the natural seam for an op-based / CRDT channel later.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from ..auth import SessionAccess, SessionCaller, require_editor
from ..config import settings
from ..errors import ApiError
from ..events import broker
from ..models import CanvasDoc, CanvasNode, DeleteNodesRequest, UpsertNodesRequest
from ..store import store
from ._responses import errors

router = APIRouter(prefix="/sessions/{sessionId}/canvas", tags=["Canvas"])


@router.get("", operation_id="getCanvas", summary="Read the whole canvas document", responses=errors(401, 403, 404))
async def get_canvas(caller: SessionCaller) -> CanvasDoc:
    """An empty board is `{"nodes": []}`, never a 404, as long as the session exists."""
    return CanvasDoc(nodes=store.get_doc(caller.session.id))


@router.put(
    "",
    operation_id="saveCanvas",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Replace the whole canvas document",
    responses=errors(400, 401, 403, 404, 409, 413),
)
async def save_canvas(caller: SessionCaller, body: CanvasDoc, request: Request) -> Response:
    """Whole-document replace. Array order is z-order and is preserved verbatim.

    Rejected with 409 when the session is ended or locked, 403 for observers.
    Emits `doc`.
    """
    require_editor(caller)
    _enforce_limits(request, body.nodes)
    store.set_doc(caller.session.id, body.nodes)
    _announce(caller)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/nodes",
    operation_id="upsertNodes",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Insert or update individual nodes",
    responses=errors(400, 401, 403, 404, 409, 413),
)
async def upsert_nodes(
    caller: SessionCaller, body: UpsertNodesRequest, request: Request
) -> Response:
    """Merges by id; nodes not mentioned are untouched.

    Ids are generated client-side (`n_` + 10 chars), so unseen ids are accepted
    as-is and never renumbered.
    """
    require_editor(caller)
    merged = store.node_count(caller.session.id) + len(body.nodes)
    _enforce_limits(request, body.nodes, projected_nodes=merged)
    store.upsert_nodes(caller.session.id, body.nodes)
    _announce(caller)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/nodes/delete",
    operation_id="deleteNodes",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete nodes by id",
    responses=errors(400, 401, 403, 404, 409),
)
async def delete_nodes(caller: SessionCaller, body: DeleteNodesRequest) -> Response:
    """Unknown ids are ignored. Arrows anchored to a deleted shape are kept —
    the frontend falls back to the arrow's last known point. Emits `doc`."""
    require_editor(caller)
    store.delete_nodes(caller.session.id, body.ids)
    _announce(caller)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _announce(caller: SessionAccess) -> None:
    """Tell everyone but the writer that the document moved."""
    broker.publish(
        caller.session.id, "doc", exclude_participant=caller.principal.participant_id
    )


def _enforce_limits(
    request: Request, nodes: list[CanvasNode], projected_nodes: int | None = None
) -> None:
    """Cheap guards against a runaway document: wire size and node count."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_canvas_bytes:
        raise ApiError(
            413,
            "canvas_too_large",
            f"Canvas document exceeds {settings.max_canvas_bytes} bytes.",
        )
    count = projected_nodes if projected_nodes is not None else len(nodes)
    if count > settings.max_canvas_nodes:
        raise ApiError(
            413,
            "canvas_too_large",
            f"Canvas document exceeds {settings.max_canvas_nodes} nodes.",
        )
