import { describe, expect, it } from "vitest";

import type { ArrowNode, CanvasNode, ShapeNode, StrokeNode, TextNode } from "@/lib/canvas-types";
import {
  arrowPoints,
  centerOf,
  edgePoint,
  hitShape,
  hitStroke,
  nodeBounds,
  shapePath,
  strokePath,
} from "./geometry";

const shape = (id: string, x: number, y: number, w = 100, h = 50): ShapeNode => ({
  type: "shape",
  id,
  kind: "service",
  label: id,
  x,
  y,
  w,
  h,
  authorId: "u1",
});

const stroke = (id: string, points: number[][]): StrokeNode => ({
  type: "stroke",
  id,
  points,
  color: "#000",
  width: 2,
  authorId: "u1",
});

describe("centerOf", () => {
  it("is the middle of the rect", () => {
    expect(centerOf(shape("a", 10, 20, 100, 50))).toEqual({ x: 60, y: 45 });
  });
});

describe("edgePoint", () => {
  // Center (50, 25); the clip box is the rect grown by 6 px on every side.
  const s = shape("a", 0, 0, 100, 50);

  it("clips a horizontal ray at the padded right edge", () => {
    expect(edgePoint(s, { x: 500, y: 25 })).toEqual({ x: 106, y: 25 });
  });

  it("clips a vertical ray at the padded bottom edge", () => {
    expect(edgePoint(s, { x: 50, y: 500 })).toEqual({ x: 50, y: 56 });
  });

  it("returns the center when the target is the center", () => {
    expect(edgePoint(s, { x: 50, y: 25 })).toEqual({ x: 50, y: 25 });
  });
});

describe("arrowPoints", () => {
  const a = shape("a", 0, 0);
  const b = shape("b", 300, 0);
  const shapes = new Map([
    ["a", a],
    ["b", b],
  ]);
  const arrow = (from: ArrowNode["from"], to: ArrowNode["to"]): ArrowNode => ({
    type: "arrow",
    id: "arr",
    from,
    to,
    label: "",
    dashed: false,
    bidirectional: false,
    authorId: "u1",
  });

  it("connects two shapes edge to edge, not center to center", () => {
    expect(arrowPoints(arrow({ shapeId: "a" }, { shapeId: "b" }), shapes)).toEqual({
      from: { x: 106, y: 25 },
      to: { x: 294, y: 25 },
    });
  });

  it("uses a free endpoint as is", () => {
    const pts = arrowPoints(arrow({ shapeId: "a" }, { x: 50, y: 400 }), shapes);
    expect(pts?.to).toEqual({ x: 50, y: 400 });
    expect(pts?.from).toEqual({ x: 50, y: 56 });
  });

  it("is null when an end points at a deleted shape", () => {
    expect(arrowPoints(arrow({ shapeId: "a" }, { shapeId: "gone" }), shapes)).toBeNull();
  });
});

describe("hit testing", () => {
  const nodes: CanvasNode[] = [shape("under", 0, 0), shape("over", 50, 0), stroke("s", [[500, 500]])];

  it("picks the topmost shape under the point", () => {
    expect(hitShape(nodes, { x: 75, y: 10 })?.id).toBe("over");
    expect(hitShape(nodes, { x: 25, y: 10 })?.id).toBe("under");
  });

  it("misses empty space", () => {
    expect(hitShape(nodes, { x: 1000, y: 1000 })).toBeNull();
  });

  it("finds a stroke within the tolerance and not beyond it", () => {
    expect(hitStroke(nodes, { x: 508, y: 500 })?.id).toBe("s");
    expect(hitStroke(nodes, { x: 520, y: 500 })).toBeNull();
  });
});

describe("nodeBounds", () => {
  it("measures a shape by its own box", () => {
    expect(nodeBounds(shape("a", 1, 2, 3, 4))).toEqual({ x: 1, y: 2, w: 3, h: 4 });
  });

  it("gives short text a minimum width", () => {
    const text: TextNode = { type: "text", id: "t", x: 10, y: 20, text: "hi", authorId: "u1" };
    expect(nodeBounds(text)).toEqual({ x: 10, y: 6, w: 40, h: 24 });
  });
});

describe("paths", () => {
  it("draws a stroke as a move followed by lines", () => {
    expect(
      strokePath([
        [0, 0],
        [10, 5],
        [20, 0],
      ]),
    ).toBe("M 0 0 L 10 5 L 20 0");
    expect(strokePath([])).toBe("");
  });

  it("closes every shape geometry", () => {
    for (const g of ["rect", "rounded", "hex", "cylinder"]) {
      expect(shapePath(shape("a", 0, 0), g)).toMatch(/^M .* Z$/);
    }
  });
});
