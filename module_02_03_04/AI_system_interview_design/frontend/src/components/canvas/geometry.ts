import type { ArrowNode, CanvasNode, Endpoint, ShapeNode, StrokeNode } from "@/lib/canvas-types";

export interface Point {
  x: number;
  y: number;
}

export const centerOf = (s: ShapeNode): Point => ({ x: s.x + s.w / 2, y: s.y + s.h / 2 });

/** Clip a ray from a rect's center towards `target` at the rect boundary. */
export function edgePoint(s: ShapeNode, target: Point): Point {
  const c = centerOf(s);
  const dx = target.x - c.x;
  const dy = target.y - c.y;
  if (dx === 0 && dy === 0) return c;
  const hw = s.w / 2 + 6;
  const hh = s.h / 2 + 6;
  const scale = Math.min(hw / Math.abs(dx || 1e-6), hh / Math.abs(dy || 1e-6));
  return { x: c.x + dx * scale, y: c.y + dy * scale };
}

export function resolveEndpoint(
  ep: Endpoint,
  shapes: Map<string, ShapeNode>,
  other: Point,
): Point | null {
  if ("shapeId" in ep) {
    const s = shapes.get(ep.shapeId);
    if (!s) return null;
    return edgePoint(s, other);
  }
  return { x: ep.x, y: ep.y };
}

export function endpointAnchor(ep: Endpoint, shapes: Map<string, ShapeNode>): Point | null {
  if ("shapeId" in ep) {
    const s = shapes.get(ep.shapeId);
    return s ? centerOf(s) : null;
  }
  return { x: ep.x, y: ep.y };
}

export function arrowPoints(
  a: ArrowNode,
  shapes: Map<string, ShapeNode>,
): { from: Point; to: Point } | null {
  const fromAnchor = endpointAnchor(a.from, shapes);
  const toAnchor = endpointAnchor(a.to, shapes);
  if (!fromAnchor || !toAnchor) return null;
  const from = resolveEndpoint(a.from, shapes, toAnchor);
  const to = resolveEndpoint(a.to, shapes, fromAnchor);
  if (!from || !to) return null;
  return { from, to };
}

export function hitShape(nodes: CanvasNode[], p: Point): ShapeNode | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i]!;
    if (n.type !== "shape") continue;
    if (p.x >= n.x && p.x <= n.x + n.w && p.y >= n.y && p.y <= n.y + n.h) return n;
  }
  return null;
}

export function hitStroke(nodes: CanvasNode[], p: Point, tol = 10): StrokeNode | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i]!;
    if (n.type !== "stroke") continue;
    for (const [x, y] of n.points) {
      if (Math.hypot((x ?? 0) - p.x, (y ?? 0) - p.y) <= tol) return n;
    }
  }
  return null;
}

export function nodeBounds(n: CanvasNode): { x: number; y: number; w: number; h: number } {
  if (n.type === "shape") return { x: n.x, y: n.y, w: n.w, h: n.h };
  if (n.type === "text") return { x: n.x, y: n.y - 14, w: Math.max(40, n.text.length * 8), h: 24 };
  if (n.type === "stroke") {
    const xs = n.points.map((p) => p[0] ?? 0);
    const ys = n.points.map((p) => p[1] ?? 0);
    const minX = Math.min(...xs, 0);
    const minY = Math.min(...ys, 0);
    return { x: minX, y: minY, w: Math.max(...xs) - minX, h: Math.max(...ys) - minY };
  }
  return { x: 0, y: 0, w: 0, h: 0 };
}

export function strokePath(points: number[][]): string {
  if (points.length === 0) return "";
  const [first, ...rest] = points;
  let d = `M ${first![0]} ${first![1]}`;
  for (const p of rest) d += ` L ${p[0]} ${p[1]}`;
  return d;
}

export function shapePath(s: ShapeNode, geometry: string): string {
  const { x, y, w, h } = s;
  if (geometry === "hex") {
    const k = Math.min(24, w * 0.18);
    return `M ${x + k} ${y} L ${x + w - k} ${y} L ${x + w} ${y + h / 2} L ${x + w - k} ${y + h} L ${x + k} ${y + h} L ${x} ${y + h / 2} Z`;
  }
  if (geometry === "cylinder") {
    const ry = Math.min(16, h * 0.18);
    return `M ${x} ${y + ry} A ${w / 2} ${ry} 0 0 1 ${x + w} ${y + ry} L ${x + w} ${y + h - ry} A ${w / 2} ${ry} 0 0 1 ${x} ${y + h - ry} Z`;
  }
  const r = geometry === "rounded" ? Math.min(28, h / 2) : 8;
  return `M ${x + r} ${y} L ${x + w - r} ${y} Q ${x + w} ${y} ${x + w} ${y + r} L ${x + w} ${y + h - r} Q ${x + w} ${y + h} ${x + w - r} ${y + h} L ${x + r} ${y + h} Q ${x} ${y + h} ${x} ${y + h - r} L ${x} ${y + r} Q ${x} ${y} ${x + r} ${y} Z`;
}
