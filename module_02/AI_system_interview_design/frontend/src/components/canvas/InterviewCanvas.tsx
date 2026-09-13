import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Eraser,
  Hand,
  MousePointer2,
  Pencil,
  Redo2,
  Trash2,
  Type,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { ArrowNode, CanvasNode, ComponentKind, ShapeNode } from "@/lib/canvas-types";
import { defFor, newNodeId } from "@/lib/canvas-types";
import type { CursorState } from "@/lib/api";
import { Palette } from "./Palette";
import {
  arrowPoints,
  centerOf,
  hitShape,
  hitStroke,
  shapePath,
  strokePath,
  type Point,
} from "./geometry";

type Tool = "select" | "pan" | "arrow" | "pen" | "text" | "eraser";

const PEN_COLORS = ["--accent-amber", "--accent-teal", "--accent-rose", "--accent-sky"];

interface Props {
  nodes: CanvasNode[];
  locked: boolean;
  authorId: string;
  canClear: boolean;
  cursors: CursorState[];
  onChange: (nodes: CanvasNode[]) => void;
  onCursor: (p: Point) => void;
}

export function InterviewCanvas({
  nodes,
  locked,
  authorId,
  canClear,
  cursors,
  onChange,
  onCursor,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 120, y: 80, zoom: 1 });
  const viewRef = useRef(view);
  viewRef.current = view;

  const [tool, setTool] = useState<Tool>("select");
  const [penColor, setPenColor] = useState(PEN_COLORS[0]!);
  const [penWidth, setPenWidth] = useState(3);
  const [selection, setSelection] = useState<string[]>([]);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const [marquee, setMarquee] = useState<{ a: Point; b: Point } | null>(null);
  const [pendingArrow, setPendingArrow] = useState<{ from: Point; fromId?: string; to: Point } | null>(
    null,
  );
  const [history, setHistory] = useState<CanvasNode[][]>([]);
  const [future, setFuture] = useState<CanvasNode[][]>([]);

  const drag = useRef<
    | { mode: "move"; ids: string[]; start: Point; origin: Record<string, Point> }
    | { mode: "resize"; id: string; start: Point; w: number; h: number }
    | { mode: "pan"; sx: number; sy: number; vx: number; vy: number }
    | { mode: "stroke"; id: string }
    | null
  >(null);

  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;

  const shapeMap = useMemo(() => {
    const m = new Map<string, ShapeNode>();
    nodes.forEach((n) => {
      if (n.type === "shape") m.set(n.id, n);
    });
    return m;
  }, [nodes]);

  const commit = useCallback(
    (next: CanvasNode[], record = true) => {
      if (record) {
        setHistory((h) => [...h.slice(-40), nodesRef.current]);
        setFuture([]);
      }
      onChange(next);
    },
    [onChange],
  );

  const toWorld = useCallback((clientX: number, clientY: number): Point => {
    const rect = wrapRef.current?.getBoundingClientRect();
    const v = viewRef.current;
    const px = clientX - (rect?.left ?? 0);
    const py = clientY - (rect?.top ?? 0);
    return { x: (px - v.x) / v.zoom, y: (py - v.y) / v.zoom };
  }, []);

  /* ------------------------------ wheel zoom ------------------------------ */
  const wheelRef = useRef<(e: WheelEvent) => void>(() => {});
  wheelRef.current = (e: WheelEvent) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const v = viewRef.current;
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    if (e.ctrlKey || e.metaKey || Math.abs(e.deltaY) > 0) {
      const dy = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1);
      if (e.shiftKey) {
        setView({ ...v, x: v.x - dy });
        return;
      }
      const next = Math.min(3, Math.max(0.25, v.zoom * Math.exp(-dy * 0.0015)));
      const k = next / v.zoom;
      setView({ zoom: next, x: px - (px - v.x) * k, y: py - (py - v.y) * k });
    }
  };

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      wheelRef.current(e);
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  /* -------------------------------- keys --------------------------------- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
        return;
      }
      if (locked) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        if (selection.length) {
          const gone = new Set(selection);
          commit(
            nodesRef.current.filter(
              (n) => !gone.has(n.id) && !(n.type === "arrow" && arrowTouches(n, gone)),
            ),
          );
          setSelection([]);
        }
      }
      if (e.key === "v") setTool("select");
      if (e.key === "a") setTool("arrow");
      if (e.key === "p") setTool("pen");
      if (e.key === "t") setTool("text");
      if (e.key === "h") setTool("pan");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, locked, commit]);

  function undo() {
    setHistory((h) => {
      if (!h.length) return h;
      const prev = h[h.length - 1]!;
      setFuture((f) => [...f, nodesRef.current]);
      onChange(prev);
      return h.slice(0, -1);
    });
  }
  function redo() {
    setFuture((f) => {
      if (!f.length) return f;
      const next = f[f.length - 1]!;
      setHistory((h) => [...h, nodesRef.current]);
      onChange(next);
      return f.slice(0, -1);
    });
  }

  /* ------------------------------ pointer -------------------------------- */

  function onPointerDown(e: React.PointerEvent) {
    const p = toWorld(e.clientX, e.clientY);
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (tool === "pan" || e.button === 1) {
      drag.current = { mode: "pan", sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
      return;
    }
    if (locked) return;

    if (tool === "pen") {
      const stroke: CanvasNode = {
        type: "stroke",
        id: newNodeId(),
        points: [[p.x, p.y]],
        color: penColor,
        width: penWidth,
        authorId,
      };
      drag.current = { mode: "stroke", id: stroke.id };
      commit([...nodes, stroke]);
      return;
    }
    if (tool === "eraser") {
      const s = hitStroke(nodes, p);
      if (s) commit(nodes.filter((n) => n.id !== s.id));
      return;
    }
    if (tool === "text") {
      const node: CanvasNode = { type: "text", id: newNodeId(), x: p.x, y: p.y, text: "", authorId };
      commit([...nodes, node]);
      setEditing({ id: node.id, value: "" });
      setTool("select");
      return;
    }
    if (tool === "arrow") {
      const shape = hitShape(nodes, p);
      if (!pendingArrow) {
        setPendingArrow(
          shape
            ? { from: centerOf(shape), fromId: shape.id, to: p }
            : { from: p, to: p },
        );
      }
      return;
    }

    // select tool
    const shape = hitShape(nodes, p);
    if (shape) {
      const ids = selection.includes(shape.id) ? selection : [shape.id];
      setSelection(ids);
      const origin: Record<string, Point> = {};
      ids.forEach((id) => {
        const n = nodes.find((x) => x.id === id);
        if (n && n.type === "shape") origin[id] = { x: n.x, y: n.y };
        if (n && n.type === "text") origin[id] = { x: n.x, y: n.y };
      });
      drag.current = { mode: "move", ids, start: p, origin };
      setHistory((h) => [...h.slice(-40), nodesRef.current]);
      return;
    }
    setSelection([]);
    setMarquee({ a: p, b: p });
  }

  function onPointerMove(e: React.PointerEvent) {
    const p = toWorld(e.clientX, e.clientY);
    onCursor(p);
    const d = drag.current;

    if (pendingArrow) setPendingArrow({ ...pendingArrow, to: p });
    if (marquee) setMarquee({ ...marquee, b: p });

    if (!d) return;
    if (d.mode === "pan") {
      setView((v) => ({ ...v, x: d.vx + (e.clientX - d.sx), y: d.vy + (e.clientY - d.sy) }));
      return;
    }
    if (d.mode === "stroke") {
      onChange(
        nodesRef.current.map((n) =>
          n.id === d.id && n.type === "stroke" ? { ...n, points: [...n.points, [p.x, p.y]] } : n,
        ),
      );
      return;
    }
    if (d.mode === "move") {
      const dx = p.x - d.start.x;
      const dy = p.y - d.start.y;
      onChange(
        nodesRef.current.map((n) => {
          const o = d.origin[n.id];
          if (!o) return n;
          if (n.type === "shape" || n.type === "text") return { ...n, x: o.x + dx, y: o.y + dy };
          return n;
        }),
      );
      return;
    }
    if (d.mode === "resize") {
      const target = nodesRef.current.find((n) => n.id === d.id);
      if (target && target.type === "shape") {
        onChange(
          nodesRef.current.map((n) =>
            n.id === d.id && n.type === "shape"
              ? {
                  ...n,
                  w: Math.max(80, d.w + (p.x - d.start.x)),
                  h: Math.max(48, d.h + (p.y - d.start.y)),
                }
              : n,
          ),
        );
      }
    }
  }

  function onPointerUp(e: React.PointerEvent) {
    const p = toWorld(e.clientX, e.clientY);
    if (drag.current) {
      const mode = drag.current.mode;
      drag.current = null;
      if (mode !== "pan") onChange(nodesRef.current);
    }
    if (marquee) {
      const x1 = Math.min(marquee.a.x, marquee.b.x);
      const x2 = Math.max(marquee.a.x, marquee.b.x);
      const y1 = Math.min(marquee.a.y, marquee.b.y);
      const y2 = Math.max(marquee.a.y, marquee.b.y);
      const picked = nodes
        .filter((n) => (n.type === "shape" || n.type === "text") && n.x >= x1 && n.x <= x2 && n.y >= y1 && n.y <= y2)
        .map((n) => n.id);
      setSelection(picked);
      setMarquee(null);
    }
    if (pendingArrow && tool === "arrow") {
      const target = hitShape(nodes, p);
      const sameStart =
        Math.hypot(p.x - pendingArrow.from.x, p.y - pendingArrow.from.y) < 6 && !target;
      if (!sameStart) {
        const arrow: ArrowNode = {
          type: "arrow",
          id: newNodeId(),
          from: pendingArrow.fromId ? { shapeId: pendingArrow.fromId } : { ...pendingArrow.from },
          to: target && target.id !== pendingArrow.fromId ? { shapeId: target.id } : { x: p.x, y: p.y },
          label: "",
          dashed: false,
          bidirectional: false,
          authorId,
        };
        commit([...nodes, arrow]);
        setPendingArrow(null);
        setTool("select");
      }
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    if (locked) return;
    const kind = e.dataTransfer.getData("application/x-sdi-component") as ComponentKind;
    if (!kind) return;
    const def = defFor(kind);
    const p = toWorld(e.clientX, e.clientY);
    const shape: ShapeNode = {
      type: "shape",
      id: newNodeId(),
      kind,
      label: def.label,
      x: p.x - def.width / 2,
      y: p.y - def.height / 2,
      w: def.width,
      h: def.height,
      authorId,
    };
    commit([...nodes, shape]);
    setSelection([shape.id]);
  }

  const selected = selection.length === 1 ? nodes.find((n) => n.id === selection[0]) : undefined;
  const editingNode = editing ? nodes.find((n) => n.id === editing.id) : undefined;

  function saveEditing() {
    if (!editing) return;
    const next = nodesRef.current
      .map((n) => {
        if (n.id !== editing.id) return n;
        if (n.type === "shape") return { ...n, label: editing.value };
        if (n.type === "text") return { ...n, text: editing.value };
        if (n.type === "arrow") return { ...n, label: editing.value };
        return n;
      })
      .filter((n) => !(n.type === "text" && n.text.trim() === ""));
    commit(next);
    setEditing(null);
  }

  const screenOf = (p: Point) => ({ x: p.x * view.zoom + view.x, y: p.y * view.zoom + view.y });

  return (
    <div className="flex h-full min-h-0 w-full">
      <aside className="hidden w-52 shrink-0 border-r border-border bg-surface md:block">
        <Palette disabled={locked} />
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* toolbar */}
        <div className="flex flex-wrap items-center gap-1 border-b border-border bg-surface px-2 py-1.5">
          {(
            [
              ["select", MousePointer2, "Select (V)"],
              ["arrow", ArrowRight, "Arrow (A)"],
              ["pen", Pencil, "Pen (P)"],
              ["text", Type, "Text (T)"],
              ["eraser", Eraser, "Erase strokes"],
              ["pan", Hand, "Pan (H)"],
            ] as const
          ).map(([id, Icon, title]) => (
            <button
              key={id}
              type="button"
              title={title}
              onClick={() => {
                setTool(id);
                setPendingArrow(null);
              }}
              className={`rounded-md border p-2 transition-colors ${
                tool === id
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-transparent text-muted-foreground hover:bg-surface-2 hover:text-foreground"
              }`}
            >
              <Icon className="h-4 w-4" />
            </button>
          ))}

          <div className="mx-2 h-6 w-px bg-border" />
          <div className="flex items-center gap-1">
            {PEN_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                title="Stroke colour"
                onClick={() => {
                  setPenColor(c);
                  setTool("pen");
                }}
                className={`h-5 w-5 rounded-full border-2 ${penColor === c ? "border-foreground" : "border-transparent"}`}
                style={{ backgroundColor: `var(${c})` }}
              />
            ))}
            <input
              type="range"
              min={1}
              max={12}
              value={penWidth}
              onChange={(e) => setPenWidth(Number(e.target.value))}
              className="ml-1 w-16 accent-[var(--primary)]"
              title="Stroke thickness"
            />
          </div>

          <div className="mx-2 h-6 w-px bg-border" />
          <button type="button" className="btn-base btn-ghost px-2 py-1.5" onClick={undo} title="Undo my last action">
            <Undo2 className="h-4 w-4" />
          </button>
          <button type="button" className="btn-base btn-ghost px-2 py-1.5" onClick={redo} title="Redo">
            <Redo2 className="h-4 w-4" />
          </button>

          <div className="mx-2 h-6 w-px bg-border" />
          <button
            type="button"
            className="btn-base btn-ghost px-2 py-1.5"
            onClick={() => setView((v) => ({ ...v, zoom: Math.max(0.25, v.zoom - 0.15) }))}
          >
            <ZoomOut className="h-4 w-4" />
          </button>
          <span className="w-12 text-center font-mono text-xs text-muted-foreground">
            {Math.round(view.zoom * 100)}%
          </span>
          <button
            type="button"
            className="btn-base btn-ghost px-2 py-1.5"
            onClick={() => setView((v) => ({ ...v, zoom: Math.min(3, v.zoom + 0.15) }))}
          >
            <ZoomIn className="h-4 w-4" />
          </button>

          {canClear && (
            <button
              type="button"
              className="btn-base btn-danger ml-auto px-2 py-1.5"
              onClick={() => {
                if (window.confirm("Clear the whole board for everyone?")) commit([]);
              }}
            >
              <Trash2 className="h-4 w-4" />
              Clear board
            </button>
          )}
        </div>

        {/* canvas */}
        <div
          ref={wrapRef}
          className="canvas-surface relative min-h-0 flex-1 overflow-hidden"
          style={{
            backgroundSize: `${24 * view.zoom}px ${24 * view.zoom}px`,
            backgroundPosition: `${view.x}px ${view.y}px`,
            cursor: tool === "pan" ? "grab" : tool === "pen" ? "crosshair" : "default",
          }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
        >
          <svg
            className="absolute inset-0 h-full w-full touch-none"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onDoubleClick={(e) => {
              const p = toWorld(e.clientX, e.clientY);
              const s = hitShape(nodes, p);
              if (s) setEditing({ id: s.id, value: s.label });
            }}
          >
            <defs>
              <marker id="arrowhead" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">
                <path d="M0,0 L10,4 L0,8 Z" fill="var(--wire)" />
              </marker>
            </defs>
            <g transform={`translate(${view.x},${view.y}) scale(${view.zoom})`}>
              {nodes.map((n) => {
                if (n.type === "stroke") {
                  return (
                    <path
                      key={n.id}
                      d={strokePath(n.points)}
                      fill="none"
                      stroke={`var(${n.color})`}
                      strokeWidth={n.width}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  );
                }
                if (n.type === "arrow") {
                  const pts = arrowPoints(n, shapeMap);
                  if (!pts) return null;
                  const mid = { x: (pts.from.x + pts.to.x) / 2, y: (pts.from.y + pts.to.y) / 2 };
                  return (
                    <g key={n.id} onDoubleClick={() => setEditing({ id: n.id, value: n.label })}>
                      <line
                        x1={pts.from.x}
                        y1={pts.from.y}
                        x2={pts.to.x}
                        y2={pts.to.y}
                        stroke="var(--wire)"
                        strokeWidth={1.8}
                        strokeDasharray={n.dashed ? "7 5" : undefined}
                        markerEnd="url(#arrowhead)"
                        markerStart={n.bidirectional ? "url(#arrowhead)" : undefined}
                      />
                      {n.label && (
                        <text
                          x={mid.x}
                          y={mid.y - 6}
                          textAnchor="middle"
                          className="font-mono"
                          fontSize={11}
                          fill="var(--muted-foreground)"
                        >
                          {n.label}
                        </text>
                      )}
                    </g>
                  );
                }
                if (n.type === "text") {
                  return (
                    <text
                      key={n.id}
                      x={n.x}
                      y={n.y}
                      fontSize={15}
                      fill="var(--foreground)"
                      onDoubleClick={() => setEditing({ id: n.id, value: n.text })}
                    >
                      {n.text}
                    </text>
                  );
                }
                const def = defFor(n.kind);
                const isSelected = selection.includes(n.id);
                return (
                  <g key={n.id}>
                    <path
                      d={shapePath(n, def.geometry)}
                      fill="var(--node-fill)"
                      stroke={isSelected ? "var(--primary)" : `var(--accent-${def.accent})`}
                      strokeWidth={isSelected ? 2.5 : 1.6}
                    />
                    <rect
                      x={n.x}
                      y={n.y}
                      width={n.w}
                      height={4}
                      fill={`var(--accent-${def.accent})`}
                      opacity={0.85}
                    />
                    <text
                      x={n.x + n.w / 2}
                      y={n.y + n.h / 2 + 5}
                      textAnchor="middle"
                      fontSize={13}
                      fill="var(--foreground)"
                    >
                      {n.label}
                    </text>
                    {isSelected && !locked && (
                      <rect
                        x={n.x + n.w - 5}
                        y={n.y + n.h - 5}
                        width={10}
                        height={10}
                        fill="var(--primary)"
                        style={{ cursor: "nwse-resize" }}
                        onPointerDown={(e) => {
                          e.stopPropagation();
                          drag.current = {
                            mode: "resize",
                            id: n.id,
                            start: toWorld(e.clientX, e.clientY),
                            w: n.w,
                            h: n.h,
                          };
                          setHistory((h) => [...h.slice(-40), nodesRef.current]);
                        }}
                      />
                    )}
                  </g>
                );
              })}

              {pendingArrow && (
                <line
                  x1={pendingArrow.from.x}
                  y1={pendingArrow.from.y}
                  x2={pendingArrow.to.x}
                  y2={pendingArrow.to.y}
                  stroke="var(--primary)"
                  strokeWidth={1.6}
                  strokeDasharray="5 4"
                  markerEnd="url(#arrowhead)"
                />
              )}
              {marquee && (
                <rect
                  x={Math.min(marquee.a.x, marquee.b.x)}
                  y={Math.min(marquee.a.y, marquee.b.y)}
                  width={Math.abs(marquee.b.x - marquee.a.x)}
                  height={Math.abs(marquee.b.y - marquee.a.y)}
                  fill="color-mix(in oklab, var(--primary) 12%, transparent)"
                  stroke="var(--primary)"
                  strokeDasharray="4 4"
                />
              )}
            </g>
          </svg>

          {/* remote cursors */}
          {cursors.map((c) => {
            const s = screenOf({ x: c.x, y: c.y });
            return (
              <div
                key={c.participantId}
                className="pointer-events-none absolute z-20 flex items-center gap-1 transition-transform duration-100"
                style={{ transform: `translate(${s.x}px, ${s.y}px)` }}
              >
                <MousePointer2 className="h-4 w-4" style={{ color: c.color }} fill={c.color} />
                <span
                  className="rounded px-1.5 py-0.5 text-[10px] font-medium text-background"
                  style={{ backgroundColor: c.color }}
                >
                  {c.name}
                </span>
              </div>
            );
          })}

          {/* inline label editor */}
          {editing && editingNode && (
            <div
              className="absolute z-30"
              style={(() => {
                const b =
                  editingNode.type === "shape"
                    ? screenOf({ x: editingNode.x, y: editingNode.y + editingNode.h / 2 - 16 })
                    : editingNode.type === "text"
                      ? screenOf({ x: editingNode.x, y: editingNode.y - 18 })
                      : { x: 16, y: 16 };
                return { left: b.x, top: b.y };
              })()}
            >
              <input
                autoFocus
                value={editing.value}
                onChange={(e) => setEditing({ ...editing, value: e.target.value })}
                onBlur={saveEditing}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveEditing();
                  if (e.key === "Escape") setEditing(null);
                }}
                className="field w-44 py-1 text-sm"
                placeholder={editingNode.type === "arrow" ? "Label, e.g. async" : "Name"}
              />
            </div>
          )}

          {locked && (
            <div className="pointer-events-none absolute bottom-3 left-1/2 z-20 -translate-x-1/2 rounded-full border border-border bg-surface px-4 py-1.5 text-xs text-muted-foreground">
              Session ended — board is read-only
            </div>
          )}
        </div>

        {/* selection inspector */}
        {selected && selected.type === "shape" && !locked && (
          <div className="flex items-center gap-2 border-t border-border bg-surface px-3 py-2 text-xs">
            <span className="label-caps">Selected</span>
            <input
              value={selected.label}
              onChange={(e) =>
                onChange(
                  nodes.map((n) => (n.id === selected.id && n.type === "shape" ? { ...n, label: e.target.value } : n)),
                )
              }
              className="field w-56 py-1"
            />
            <button
              type="button"
              className="btn-base btn-ghost px-2 py-1"
              onClick={() => {
                const copy: ShapeNode = { ...selected, id: newNodeId(), x: selected.x + 24, y: selected.y + 24 };
                commit([...nodes, copy]);
                setSelection([copy.id]);
              }}
            >
              Duplicate
            </button>
            <button
              type="button"
              className="btn-base btn-danger px-2 py-1"
              onClick={() => {
                const gone = new Set([selected.id]);
                commit(
                  nodes.filter((n) => !gone.has(n.id) && !(n.type === "arrow" && arrowTouches(n, gone))),
                );
                setSelection([]);
              }}
            >
              Delete
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function arrowTouches(a: ArrowNode, ids: Set<string>) {
  const f = "shapeId" in a.from && ids.has(a.from.shapeId);
  const t = "shapeId" in a.to && ids.has(a.to.shapeId);
  return f || t;
}
