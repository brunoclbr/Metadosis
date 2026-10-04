export const BRAIN_NODE_TYPES = [
  "process",
  "session",
  "step",
  "decision",
  "reason",
  "guardrail",
  "exception",
  "tool",
  "artifact",
  "evidence",
] as const;

export type BrainNodeType = (typeof BRAIN_NODE_TYPES)[number];
export type BrainProperties = Record<string, string | number | boolean | null>;

export type BrainNode = {
  id: string;
  type: BrainNodeType;
  label: string;
  properties: BrainProperties;
};

export type BrainEdge = {
  source: string;
  target: string;
  type: string;
};

export type BrainGraph = {
  process: BrainNode;
  nodes: BrainNode[];
  edges: BrainEdge[];
};

export class BrainGraphError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function getBrainGraph(
  processId: string,
  signal?: AbortSignal,
): Promise<BrainGraph> {
  const response = await fetch(
    `/api/brain/processes/${encodeURIComponent(processId)}/graph`,
    { cache: "no-store", signal },
  );
  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    throw new BrainGraphError("The Brain couldn't be loaded.", response.status);
  }
  if (!isBrainGraph(payload)) {
    throw new BrainGraphError("The Brain couldn't be loaded.", 502);
  }
  return payload;
}

function isBrainGraph(value: unknown): value is BrainGraph {
  if (!value || typeof value !== "object") return false;
  const graph = value as Partial<BrainGraph>;
  return (
    isBrainNode(graph.process) &&
    Array.isArray(graph.nodes) &&
    graph.nodes.every(isBrainNode) &&
    Array.isArray(graph.edges) &&
    graph.edges.every(isBrainEdge)
  );
}

function isBrainNode(value: unknown): value is BrainNode {
  if (!value || typeof value !== "object") return false;
  const node = value as Partial<BrainNode>;
  return (
    typeof node.id === "string" &&
    typeof node.label === "string" &&
    typeof node.type === "string" &&
    BRAIN_NODE_TYPES.includes(node.type as BrainNodeType) &&
    Boolean(node.properties) &&
    typeof node.properties === "object"
  );
}

function isBrainEdge(value: unknown): value is BrainEdge {
  if (!value || typeof value !== "object") return false;
  const edge = value as Partial<BrainEdge>;
  return (
    typeof edge.source === "string" &&
    typeof edge.target === "string" &&
    typeof edge.type === "string"
  );
}
