"use client";

import dagre from "@dagrejs/dagre";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type {
  BrainEdge,
  BrainGraph,
  BrainNode,
  BrainNodeType,
} from "@/lib/brain-graph-api";
import type { Process } from "@/lib/process-api";
import { useBrainGraph } from "@/lib/use-brain-graph";

type BrainPanelProps = {
  hidden: boolean;
  processes: readonly Process[];
  selectedProcess: Process | null;
  isLoadingProcesses: boolean;
  processError: string | null;
  onSelectProcess: (processId: string) => void;
};

type GraphNodeData = {
  brainNode: BrainNode;
  label: ReactNode;
};

const PRIMARY_EDGE_TYPES = new Set([
  "HAS_STEP",
  "HAS_DECISION",
  "HAS_REASON",
  "HAS_GUARDRAIL",
  "HAS_EXCEPTION",
  "LEARNED_FROM",
  "SUPPORTED_BY",
  "USES",
  "USES_ARTIFACT",
]);

const NODE_SIZE: Record<BrainNodeType, { width: number; height: number }> = {
  process: { width: 230, height: 82 },
  step: { width: 215, height: 88 },
  decision: { width: 210, height: 88 },
  reason: { width: 190, height: 78 },
  guardrail: { width: 215, height: 88 },
  exception: { width: 200, height: 82 },
  session: { width: 150, height: 58 },
  evidence: { width: 150, height: 58 },
  tool: { width: 170, height: 66 },
  artifact: { width: 170, height: 66 },
};

export function BrainPanel({
  hidden,
  isLoadingProcesses,
  onSelectProcess,
  processError,
  processes,
  selectedProcess,
}: BrainPanelProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const { error, graph, isEmpty, isLoading, retry } = useBrainGraph(
    selectedProcess?.id ?? null,
    !hidden,
  );

  useEffect(() => {
    if (!hidden && !selectedProcess && processes.length === 1) {
      onSelectProcess(processes[0].id);
    }
  }, [hidden, onSelectProcess, processes, selectedProcess]);

  const selectedNode = graph
    ? allBrainNodes(graph).find((node) => node.id === selectedNodeId) ?? null
    : null;

  return (
    <section
      id="brain-panel"
      className="mode-panel brain-panel"
      role="tabpanel"
      aria-labelledby="brain-tab"
      hidden={hidden}
    >
      <header className="brain-header">
        <div>
          <span className="eyebrow">Brain</span>
          <label className="brain-picker-label" htmlFor="brain-process-select">
            Knowledge
          </label>
        </div>
        <select
          className="field field-select brain-process-select"
          id="brain-process-select"
          value={selectedProcess?.id ?? ""}
          disabled={isLoadingProcesses || processes.length === 0}
          onChange={(event) => {
            if (event.target.value) onSelectProcess(event.target.value);
          }}
        >
          <option value="" disabled>
            {isLoadingProcesses
              ? "Opening knowledge…"
              : processes.length === 0
                ? "No taught processes yet"
                : "Choose knowledge"}
          </option>
          {processes.map((process) => (
            <option value={process.id} key={process.id}>
              {process.title}
            </option>
          ))}
        </select>
      </header>

      <div className="brain-canvas" aria-live="polite">
        {isLoading || isLoadingProcesses ? (
          <BrainMessage title="Opening the Brain…" />
        ) : processError && processes.length === 0 ? (
          <BrainMessage
            title="The Brain couldn't be loaded."
            body="Please try again in a moment."
          />
        ) : processes.length === 0 ? (
          <BrainMessage
            title="Nothing captured here yet."
            body="Teach Metadosis a process and its knowledge will appear here."
          />
        ) : !selectedProcess ? (
          <BrainMessage
            title="Choose what Metadosis has learned."
            body="Select a process above to open its knowledge."
          />
        ) : isEmpty ? (
          <BrainMessage
            title="Nothing captured here yet."
            body="Teach Metadosis this process and its knowledge will appear here."
          />
        ) : error ? (
          <BrainMessage
            title="The Brain couldn't be loaded."
            body="Please try again in a moment."
            action={<button className="btn" onClick={retry}>Try again</button>}
          />
        ) : graph ? (
          <KnowledgeGraph
            graph={graph}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
        ) : null}

        {graph && selectedNode && (
          <NodeDetails
            graph={graph}
            node={selectedNode}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>
    </section>
  );
}

function BrainMessage({
  action,
  body,
  title,
}: {
  action?: ReactNode;
  body?: string;
  title: string;
}) {
  return (
    <div className="brain-message">
      <span className="brain-message-mark" aria-hidden="true">M</span>
      <strong>{title}</strong>
      {body && <p>{body}</p>}
      {action}
    </div>
  );
}

function KnowledgeGraph({
  graph,
  onSelectNode,
  selectedNodeId,
}: {
  graph: BrainGraph;
  onSelectNode: (nodeId: string | null) => void;
  selectedNodeId: string | null;
}) {
  const { edges, nodes } = useMemo(
    () => layoutGraph(graph, selectedNodeId),
    [graph, selectedNodeId],
  );
  const handleNodeClick: NodeMouseHandler<Node<GraphNodeData>> = (_, node) => {
    onSelectNode(node.id);
  };

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable
      fitView
      fitViewOptions={{ padding: 0.18, maxZoom: 1.15 }}
      minZoom={0.22}
      maxZoom={1.65}
      onNodeClick={handleNodeClick}
      onPaneClick={() => onSelectNode(null)}
      proOptions={{ hideAttribution: true }}
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={22}
        size={1}
        color="var(--line)"
      />
      <Controls showInteractive={false} position="bottom-left" />
    </ReactFlow>
  );
}

function layoutGraph(
  graph: BrainGraph,
  selectedNodeId: string | null,
): { nodes: Node<GraphNodeData>[]; edges: Edge[] } {
  const graphNodes = allBrainNodes(graph);
  const knownIds = new Set(graphNodes.map((node) => node.id));
  const validEdges = graph.edges.filter(
    (edge) => knownIds.has(edge.source) && knownIds.has(edge.target),
  );
  const layout = new dagre.graphlib.Graph();
  layout.setDefaultEdgeLabel(() => ({}));
  layout.setGraph({ rankdir: "TB", ranksep: 92, nodesep: 34, edgesep: 18 });

  graphNodes.forEach((node) => layout.setNode(node.id, NODE_SIZE[node.type]));
  validEdges
    .filter((edge) => PRIMARY_EDGE_TYPES.has(edge.type) && edge.type !== "CONTRIBUTED")
    .forEach((edge) => layout.setEdge(edge.source, edge.target));
  dagre.layout(layout);

  return {
    nodes: graphNodes.map((brainNode) => {
      const size = NODE_SIZE[brainNode.type];
      const position = layout.node(brainNode.id);
      return {
        id: brainNode.id,
        position: {
          x: position.x - size.width / 2,
          y: position.y - size.height / 2,
        },
        data: {
          brainNode,
          label: <GraphNodeLabel node={brainNode} />,
        },
        className: `brain-node brain-node-${brainNode.type}${
          selectedNodeId === brainNode.id ? " is-selected" : ""
        }`,
        style: size,
        selectable: true,
      };
    }),
    edges: validEdges.map((edge, index) => toFlowEdge(edge, index)),
  };
}

function toFlowEdge(edge: BrainEdge, index: number): Edge {
  const isProvenance = ["SUPPORTED_BY", "FROM_SESSION", "CONTRIBUTED"].includes(
    edge.type,
  );
  return {
    id: `${edge.source}-${edge.type}-${edge.target}-${index}`,
    source: edge.source,
    target: edge.target,
    className: isProvenance ? "brain-edge is-provenance" : "brain-edge",
    markerEnd: isProvenance
      ? undefined
      : { type: MarkerType.ArrowClosed, width: 13, height: 13 },
    style: {
      stroke: isProvenance ? "var(--line)" : "var(--muted)",
      strokeDasharray: isProvenance ? "4 5" : undefined,
      strokeWidth: isProvenance ? 1 : 1.25,
    },
  };
}

function GraphNodeLabel({ node }: { node: BrainNode }) {
  const label = nodeLabel(node);
  return (
    <div className="brain-node-content">
      <span>{nodeTypeLabel(node.type)}</span>
      <strong>{label}</strong>
      {node.type === "step" && typeof node.properties.order === "number" && (
        <i>{String(node.properties.order).padStart(2, "0")}</i>
      )}
    </div>
  );
}

function NodeDetails({
  graph,
  node,
  onClose,
}: {
  graph: BrainGraph;
  node: BrainNode;
  onClose: () => void;
}) {
  const evidence = evidenceForNode(graph, node);
  const visibleProperties = Object.entries(node.properties).filter(
    ([key, value]) =>
      value !== null &&
      value !== "" &&
      !["knowledge_document_id", "conversation_id", "local_id"].includes(key),
  );

  return (
    <aside className="brain-details" aria-label={`${nodeTypeLabel(node.type)} details`}>
      <button className="brain-details-close" type="button" onClick={onClose} aria-label="Close details">
        ×
      </button>
      <span className="eyebrow">{nodeTypeLabel(node.type)}</span>
      <h2>{nodeLabel(node)}</h2>
      {visibleProperties.length > 0 && (
        <dl>
          {visibleProperties.map(([key, value]) => (
            <div key={key}>
              <dt>{propertyLabel(key)}</dt>
              <dd>{formatProperty(key, value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {evidence.length > 0 && (
        <div className="brain-provenance">
          <span className="eyebrow">Learned from</span>
          {evidence.slice(0, 4).map((item) => (
            <p key={item.id}>
              <strong>{evidenceLabel(item)}</strong>
              {typeof item.properties.time_in_call_secs === "number" && (
                <span>{formatTime(item.properties.time_in_call_secs)} · Expert session</span>
              )}
            </p>
          ))}
        </div>
      )}
    </aside>
  );
}

function evidenceForNode(graph: BrainGraph, node: BrainNode): BrainNode[] {
  if (node.type === "evidence") return [node];
  const evidenceIds = new Set(
    graph.edges
      .filter((edge) => edge.source === node.id && edge.type === "SUPPORTED_BY")
      .map((edge) => edge.target),
  );
  return graph.nodes.filter(
    (candidate) => candidate.type === "evidence" && evidenceIds.has(candidate.id),
  );
}

function allBrainNodes(graph: BrainGraph): BrainNode[] {
  return [graph.process, ...graph.nodes.filter((node) => node.id !== graph.process.id)];
}

function nodeLabel(node: BrainNode): string {
  if (node.type === "session") return "Expert session";
  if (node.type === "evidence") return evidenceLabel(node);
  return node.label;
}

function nodeTypeLabel(type: BrainNodeType): string {
  return type === "evidence" ? "Source" : type.replaceAll("_", " ");
}

function evidenceLabel(node: BrainNode): string {
  const source = node.properties.source_type ?? node.label;
  if (source === "transcript_turn") return "Expert transcript";
  if (source === "screen_observation") return "Screen observation";
  if (source === "camera_observation") return "Camera observation";
  return "Expert evidence";
}

function propertyLabel(key: string): string {
  return key.replaceAll("_", " ");
}

function formatProperty(
  key: string,
  value: string | number | boolean | null,
): string {
  if (key === "time_in_call_secs" && typeof value === "number") return formatTime(value);
  return String(value);
}

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}
