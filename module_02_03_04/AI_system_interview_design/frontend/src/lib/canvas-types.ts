export type ComponentKind =
  | "client"
  | "load-balancer"
  | "api-gateway"
  | "service"
  | "database"
  | "nosql"
  | "cache"
  | "queue"
  | "llm"
  | "cdn"
  | "storage"
  | "box";

export type ShapeGeometry = "rect" | "cylinder" | "rounded" | "hex";

export interface ComponentDef {
  kind: ComponentKind;
  label: string;
  geometry: ShapeGeometry;
  accent: string; // css var name suffix
  width: number;
  height: number;
}

export const COMPONENT_LIBRARY: ComponentDef[] = [
  { kind: "client", label: "Client / User", geometry: "rounded", accent: "sky", width: 150, height: 72 },
  { kind: "load-balancer", label: "Load Balancer", geometry: "hex", accent: "teal", width: 168, height: 76 },
  { kind: "api-gateway", label: "API Gateway", geometry: "rect", accent: "teal", width: 168, height: 76 },
  { kind: "service", label: "Service", geometry: "rect", accent: "amber", width: 160, height: 80 },
  { kind: "database", label: "Database (SQL)", geometry: "cylinder", accent: "lime", width: 150, height: 96 },
  { kind: "nosql", label: "NoSQL Store", geometry: "cylinder", accent: "lime", width: 150, height: 96 },
  { kind: "cache", label: "Cache", geometry: "rounded", accent: "rose", width: 140, height: 72 },
  { kind: "queue", label: "Queue / Broker", geometry: "rect", accent: "violet", width: 176, height: 68 },
  { kind: "llm", label: "LLM / AI Service", geometry: "rounded", accent: "fuchsia", width: 168, height: 80 },
  { kind: "cdn", label: "CDN", geometry: "hex", accent: "sky", width: 140, height: 72 },
  { kind: "storage", label: "Object Storage", geometry: "cylinder", accent: "orange", width: 150, height: 92 },
  { kind: "box", label: "Generic Box", geometry: "rect", accent: "slate", width: 150, height: 76 },
];

export function defFor(kind: ComponentKind): ComponentDef {
  return COMPONENT_LIBRARY.find((c) => c.kind === kind) ?? COMPONENT_LIBRARY[COMPONENT_LIBRARY.length - 1]!;
}

export interface ShapeNode {
  type: "shape";
  id: string;
  kind: ComponentKind;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  authorId: string;
}

export type Endpoint = { shapeId: string } | { x: number; y: number };

export interface ArrowNode {
  type: "arrow";
  id: string;
  from: Endpoint;
  to: Endpoint;
  label: string;
  dashed: boolean;
  bidirectional: boolean;
  authorId: string;
}

export interface StrokeNode {
  type: "stroke";
  id: string;
  points: number[][];
  color: string;
  width: number;
  authorId: string;
}

export interface TextNode {
  type: "text";
  id: string;
  x: number;
  y: number;
  text: string;
  authorId: string;
}

export type CanvasNode = ShapeNode | ArrowNode | StrokeNode | TextNode;

export interface CanvasDoc {
  nodes: CanvasNode[];
}

export const emptyDoc = (): CanvasDoc => ({ nodes: [] });

/**
 * Node ids are generated here, on the client: the backend accepts ids it has
 * never seen and never renumbers them, which is what lets an edit be drawn
 * optimistically before the save lands.
 */
export function newNodeId(): string {
  const chars = "abcdefghijkmnpqrstuvwxyz23456789";
  let out = "";
  for (let i = 0; i < 10; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return `n_${out}`;
}

export function isShape(n: CanvasNode): n is ShapeNode {
  return n.type === "shape";
}
