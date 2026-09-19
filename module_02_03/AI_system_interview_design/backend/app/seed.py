"""Demo data, so the frontend has something to render on a cold start.

Seeded once, into whatever database `LOOPBOARD_DATABASE_URL` points at, and
only while it is still empty — a restart against a persistent database keeps
whatever the last run left behind.

Two interviewer accounts (sessions are owned, and `GET /sessions` only returns
the caller's own, so the second account proves the isolation), five sessions
across live / ended / empty, and a fully drawn board on each of the busy ones.

Set `LOOPBOARD_SEED=0` to skip it.
"""

from __future__ import annotations

from .auth import hash_password
from .models import (
    ArrowNode,
    CanvasNode,
    ComponentKind,
    CursorState,
    PointEndpoint,
    Role,
    ShapeEndpoint,
    ShapeNode,
    StrokeNode,
    TextNode,
)
from .store import Store, now_ms

DEMO_PASSWORD = "loopboard-demo"

MINUTE = 60_000
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def shape(node_id: str, kind: str, label: str, x: float, y: float, author: str,
          w: float = 160, h: float = 80) -> ShapeNode:
    return ShapeNode(
        id=node_id, kind=ComponentKind(kind), label=label, x=x, y=y, w=w, h=h, authorId=author
    )


def arrow(node_id: str, src: str, dst: str, author: str, label: str = "",
          dashed: bool = False, bidirectional: bool = False) -> ArrowNode:
    return ArrowNode(
        id=node_id,
        from_=ShapeEndpoint(shapeId=src),
        to=ShapeEndpoint(shapeId=dst),
        label=label,
        dashed=dashed,
        bidirectional=bidirectional,
        authorId=author,
    )


def note(node_id: str, x: float, y: float, text: str, author: str) -> TextNode:
    return TextNode(id=node_id, x=x, y=y, text=text, authorId=author)


def seed(store: Store) -> None:
    """Populate `store` in place. Safe to call only on an empty store."""
    now = now_ms()
    password_hash = hash_password(DEMO_PASSWORD)

    alex = store.create_account("alex@loopboard.dev", "Alex Rivera", password_hash)
    sam = store.create_account("sam@loopboard.dev", "Sam Okafor", password_hash)

    _seed_url_shortener(store, alex.id, now)
    _seed_chat_system(store, alex.id, now)
    _seed_rate_limiter_ended(store, alex.id, now)
    _seed_empty_board(store, alex.id, now)
    _seed_other_interviewer(store, sam.id, now)


# Fixed ids so a developer can deep-link straight to a seeded board.
URL_SHORTENER_ID = "k7m2xp9qrt4wnb3d"
CHAT_SYSTEM_ID = "q4ztv8hdr2mkp6sn"
RATE_LIMITER_ID = "b3wn7cfk9xqm2rvd"
EMPTY_BOARD_ID = "t8hq3mz5xkbn7wrd"
OTHER_OWNER_ID = "z6rkp2mq4xhtn9bw"


def _place(store: Store, session_id: str, nodes: list[CanvasNode]) -> None:
    store.set_doc(session_id, nodes)


def _new_session(store: Store, owner_id: str, title: str, host: str, demo_id: str,
                 created_at: int) -> str:
    record = store.create_session(
        owner_id, title, host, session_id=demo_id, created_at=created_at
    )
    return record.id


def _seed_url_shortener(store: Store, owner_id: str, now: int) -> None:
    session_id = _new_session(
        store,
        owner_id,
        "Design a URL shortener — Senior Backend",
        "Alex Rivera",
        URL_SHORTENER_ID,
        now - 35 * MINUTE,
    )

    host, _ = store.join(session_id, "Alex Rivera", Role.interviewer)
    candidate, _ = store.join(session_id, "Jordan Hale", Role.candidate)
    observer, _ = store.join(session_id, "Priya Natarajan", Role.observer)

    nodes: list[CanvasNode] = [
        shape("n_url_client", "client", "Browser / curl", 60, 200, host.id, w=150, h=72),
        shape("n_url_cdn", "cdn", "CDN (302 cache)", 270, 80, candidate.id, w=140, h=72),
        shape("n_url_gateway", "api-gateway", "API Gateway", 270, 200, candidate.id, w=168, h=76),
        shape("n_url_write", "service", "Shorten Service", 510, 120, candidate.id),
        shape("n_url_read", "service", "Redirect Service", 510, 300, candidate.id),
        shape("n_url_cache", "cache", "Redis — slug→url", 740, 300, candidate.id, w=160, h=72),
        shape("n_url_db", "database", "Postgres — links", 740, 120, candidate.id, w=160, h=96),
        shape("n_url_queue", "queue", "Kafka — click events", 740, 460, candidate.id, w=176, h=68),
        shape("n_url_worker", "service", "Analytics Worker", 980, 460, candidate.id),
        shape("n_url_olap", "nosql", "ClickHouse — clicks", 1200, 460, candidate.id, w=160, h=96),
        arrow("n_url_a1", "n_url_client", "n_url_gateway", candidate.id, label="GET /{slug}"),
        arrow("n_url_a2", "n_url_client", "n_url_cdn", candidate.id, label="hot slugs", dashed=True),
        arrow("n_url_a3", "n_url_gateway", "n_url_write", candidate.id, label="POST /links"),
        arrow("n_url_a4", "n_url_gateway", "n_url_read", candidate.id),
        arrow("n_url_a5", "n_url_write", "n_url_db", candidate.id, label="insert slug"),
        arrow("n_url_a6", "n_url_read", "n_url_cache", candidate.id, bidirectional=True),
        arrow("n_url_a7", "n_url_cache", "n_url_db", candidate.id, label="miss", dashed=True),
        arrow("n_url_a8", "n_url_read", "n_url_queue", candidate.id, label="async", dashed=True),
        arrow("n_url_a9", "n_url_queue", "n_url_worker", candidate.id),
        arrow("n_url_a10", "n_url_worker", "n_url_olap", candidate.id, label="batch insert"),
        note("n_url_t1", 510, 60, "base62(snowflake id) — 7 chars ≈ 3.5T slugs", candidate.id),
        note("n_url_t2", 740, 240, "99% of reads served from cache", candidate.id),
        note("n_url_t3", 60, 420, "100M writes/day, 10:1 read:write", host.id),
        StrokeNode(
            id="n_url_s1",
            points=[[700, 90], [760, 86], [820, 92], [880, 104], [900, 130]],
            color="#f5b83d",
            width=3,
            authorId=host.id,
        ),
        ArrowNode(
            id="n_url_a11",
            from_=PointEndpoint(x=300, y=560),
            to=ShapeEndpoint(shapeId="n_url_olap"),
            label="dashboards read here",
            dashed=True,
            bidirectional=False,
            authorId=host.id,
        ),
    ]
    _place(store, session_id, nodes)

    store.put_cursor(
        session_id,
        CursorState(
            participantId=candidate.id,
            name=candidate.name,
            color=candidate.color,
            x=812,
            y=332,
            at=now - 1_200,
        ),
    )
    store.put_cursor(
        session_id,
        CursorState(
            participantId=observer.id,
            name=observer.name,
            color=observer.color,
            x=352,
            y=188,
            at=now - 4_000,
        ),
    )


def _seed_chat_system(store: Store, owner_id: str, now: int) -> None:
    session_id = _new_session(
        store,
        owner_id,
        "Design a group chat backend — Staff",
        "Alex Rivera",
        CHAT_SYSTEM_ID,
        now - 3 * HOUR,
    )
    host, _ = store.join(session_id, "Alex Rivera", Role.interviewer)
    candidate, _ = store.join(session_id, "Mina Aydin", Role.candidate)

    nodes: list[CanvasNode] = [
        shape("n_chat_client", "client", "Mobile client", 80, 220, candidate.id, w=150, h=72),
        shape("n_chat_lb", "load-balancer", "WS Load Balancer", 300, 220, candidate.id, w=168, h=76),
        shape("n_chat_ws", "service", "Gateway (WebSocket)", 540, 220, candidate.id, w=180, h=80),
        shape("n_chat_fanout", "service", "Fanout Service", 790, 120, candidate.id),
        shape("n_chat_presence", "cache", "Redis — presence", 790, 340, candidate.id, w=160, h=72),
        shape("n_chat_queue", "queue", "Message bus", 1030, 120, candidate.id, w=176, h=68),
        shape("n_chat_store", "nosql", "Cassandra — messages", 1030, 320, candidate.id, w=176, h=96),
        shape("n_chat_blob", "storage", "S3 — attachments", 540, 440, candidate.id, w=160, h=92),
        arrow("n_chat_a1", "n_chat_client", "n_chat_lb", candidate.id, bidirectional=True),
        arrow("n_chat_a2", "n_chat_lb", "n_chat_ws", candidate.id, label="sticky"),
        arrow("n_chat_a3", "n_chat_ws", "n_chat_fanout", candidate.id, label="send"),
        arrow("n_chat_a4", "n_chat_ws", "n_chat_presence", candidate.id, bidirectional=True),
        arrow("n_chat_a5", "n_chat_fanout", "n_chat_queue", candidate.id, dashed=True),
        arrow("n_chat_a6", "n_chat_fanout", "n_chat_store", candidate.id, label="persist"),
        arrow("n_chat_a7", "n_chat_client", "n_chat_blob", candidate.id, label="presigned PUT", dashed=True),
        note("n_chat_t1", 1030, 250, "partition by (channel_id, bucket)", candidate.id),
        note("n_chat_t2", 300, 120, "ordering: per-channel seq no.", host.id),
    ]
    _place(store, session_id, nodes)
    store.put_cursor(
        session_id,
        CursorState(
            participantId=host.id,
            name=host.name,
            color=host.color,
            x=1_060,
            y=268,
            at=now - 800,
        ),
    )


def _seed_rate_limiter_ended(store: Store, owner_id: str, now: int) -> None:
    session_id = _new_session(
        store,
        owner_id,
        "Design a distributed rate limiter — Mid Backend",
        "Alex Rivera",
        RATE_LIMITER_ID,
        now - 2 * DAY,
    )
    record = store.get_session(session_id)
    assert record is not None
    author = "p_seedauthor"
    nodes: list[CanvasNode] = [
        shape("n_rl_client", "client", "Clients", 80, 200, author, w=150, h=72),
        shape("n_rl_edge", "api-gateway", "Edge / Envoy", 300, 200, author, w=168, h=76),
        shape("n_rl_limiter", "service", "Limiter (token bucket)", 540, 200, author, w=184, h=80),
        shape("n_rl_redis", "cache", "Redis cluster", 800, 200, author, w=160, h=72),
        shape("n_rl_api", "service", "Upstream API", 540, 380, author),
        arrow("n_rl_a1", "n_rl_client", "n_rl_edge", author),
        arrow("n_rl_a2", "n_rl_edge", "n_rl_limiter", author, label="check(key)"),
        arrow("n_rl_a3", "n_rl_limiter", "n_rl_redis", author, label="INCR + EXPIRE", bidirectional=True),
        arrow("n_rl_a4", "n_rl_limiter", "n_rl_api", author, label="allowed"),
        note("n_rl_t1", 800, 120, "fallback: local bucket if Redis is down", author),
        note("n_rl_t2", 80, 380, "verdict: strong on trade-offs, light on failure modes", author),
    ]
    _place(store, session_id, nodes)
    store.end_session(record, ended_at=now - 2 * DAY + 52 * MINUTE)


def _seed_empty_board(store: Store, owner_id: str, now: int) -> None:
    _new_session(
        store,
        owner_id,
        "",  # exercises the "Untitled interview" fallback
        "",  # and the "Interviewer" one
        EMPTY_BOARD_ID,
        now - 10 * MINUTE,
    )


def _seed_other_interviewer(store: Store, owner_id: str, now: int) -> None:
    session_id = _new_session(
        store,
        owner_id,
        "Design a feature flag service — Senior",
        "Sam Okafor",
        OTHER_OWNER_ID,
        now - 26 * HOUR,
    )
    author = "p_seedauthor"
    _place(
        store,
        session_id,
        [
            shape("n_ff_sdk", "client", "App SDK", 80, 180, author, w=150, h=72),
            shape("n_ff_cdn", "cdn", "Config CDN", 300, 180, author, w=140, h=72),
            shape("n_ff_api", "service", "Flag Service", 520, 180, author),
            shape("n_ff_db", "database", "Postgres — rules", 740, 180, author, w=160, h=96),
            arrow("n_ff_a1", "n_ff_sdk", "n_ff_cdn", author, label="poll 30s", dashed=True),
            arrow("n_ff_a2", "n_ff_cdn", "n_ff_api", author),
            arrow("n_ff_a3", "n_ff_api", "n_ff_db", author),
        ],
    )
