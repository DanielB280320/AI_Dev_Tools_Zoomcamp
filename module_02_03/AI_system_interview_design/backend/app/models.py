"""Wire models — one per schema in openapi.yaml.

Every object the contract declares `additionalProperties: false` extends
`Strict`, so an unexpected key is a 400 rather than a silently dropped field.
Field names stay camelCase to match the contract exactly; the one exception is
`ArrowNode.from`, a Python keyword, which is aliased.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Timestamp = Annotated[int, Field(description="Epoch milliseconds, not seconds.")]
HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(str, Enum):
    interviewer = "interviewer"
    candidate = "candidate"
    observer = "observer"


class SessionStatus(str, Enum):
    live = "live"
    ended = "ended"


class ComponentKind(str, Enum):
    client = "client"
    load_balancer = "load-balancer"
    api_gateway = "api-gateway"
    service = "service"
    database = "database"
    nosql = "nosql"
    cache = "cache"
    queue = "queue"
    llm = "llm"
    cdn = "cdn"
    storage = "storage"
    box = "box"


# --------------------------------- sessions ---------------------------------


class Session(Strict):
    id: str
    title: str
    hostName: str
    status: SessionStatus
    createdAt: Timestamp
    endedAt: Timestamp | None
    canvasLocked: bool


class CreateSessionRequest(Strict):
    title: str = Field(max_length=200)
    hostName: str = Field(max_length=100)


# ------------------------------- participants -------------------------------


class Participant(Strict):
    id: str
    name: str
    role: Role
    color: HexColor
    lastSeen: Timestamp


class JoinSessionRequest(Strict):
    name: str = Field(max_length=100)
    role: Role


class JoinSessionResponse(Participant):
    token: str = Field(description="Bearer token scoped to this session and participant.")


class LeaveBeaconRequest(Strict):
    """Body for `POST .../leave`.

    `navigator.sendBeacon` cannot set an `Authorization` header, so the token
    may travel in the body instead.
    """

    token: str | None = None


# ---------------------------------- cursors ---------------------------------


class CursorState(Strict):
    participantId: str
    name: str
    color: HexColor
    x: float
    y: float
    at: Timestamp


# ---------------------------------- canvas ----------------------------------


class ShapeEndpoint(Strict):
    shapeId: str


class PointEndpoint(Strict):
    x: float
    y: float


Endpoint = ShapeEndpoint | PointEndpoint


class ShapeNode(Strict):
    type: Literal["shape"] = "shape"
    id: str
    kind: ComponentKind
    label: str
    x: float
    y: float
    w: float
    h: float
    authorId: str


class ArrowNode(Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["arrow"] = "arrow"
    id: str
    from_: Endpoint = Field(alias="from")
    to: Endpoint
    label: str
    dashed: bool
    bidirectional: bool
    authorId: str


Point = Annotated[list[float], Field(min_length=2, max_length=2)]


class StrokeNode(Strict):
    type: Literal["stroke"] = "stroke"
    id: str
    points: list[Point]
    color: str
    width: float
    authorId: str


class TextNode(Strict):
    type: Literal["text"] = "text"
    id: str
    x: float
    y: float
    text: str
    authorId: str


CanvasNode = Annotated[
    ShapeNode | ArrowNode | StrokeNode | TextNode, Field(discriminator="type")
]


#: Validates a node back out of its stored JSON, picking the member of the
#: union from `type` exactly as request parsing does.
CanvasNodeAdapter: TypeAdapter[CanvasNode] = TypeAdapter(CanvasNode)


class CanvasDoc(Strict):
    nodes: list[CanvasNode]


class UpsertNodesRequest(Strict):
    nodes: list[CanvasNode]


class DeleteNodesRequest(Strict):
    ids: list[str]


# ----------------------------- interviewer auth -----------------------------


class InterviewerAccount(Strict):
    """Public view of an interviewer account — never carries the password hash."""

    id: str
    email: str
    name: str


class RegisterRequest(Strict):
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=100)


class LoginRequest(Strict):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class AuthTokenResponse(Strict):
    token: str
    interviewer: InterviewerAccount


# ----------------------------------- misc -----------------------------------


class Error(Strict):
    error: str
    message: str | None = None
