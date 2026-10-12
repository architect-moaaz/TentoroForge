"use client";

/**
 * The records on the idea board, drawn: one card per record with its
 * fields, a line for each link (one, or many). Laid out by dagre.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ReactFlow, Background, BackgroundVariant, Controls, Handle, Position, MarkerType,
  type Node, type Edge, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Board } from "./types";

type CardData = { name: string; fields: { name: string; type?: string }[] };
const W = 220;
const height = (d: CardData) => 40 + Math.min(d.fields.length, 10) * 20 + (d.fields.length > 10 ? 20 : 0);

function RecordCard({ data }: NodeProps<Node<CardData>>) {
  return (
    <div className="rounded-lg border bg-background shadow-sm text-xs" style={{ width: W }}>
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <div className="px-3 py-2 font-semibold border-b bg-muted/50 rounded-t-lg">{data.name}</div>
      <div className="px-3 py-1.5 space-y-0.5">
        {data.fields.slice(0, 10).map((f) => (
          <div key={f.name} className="flex justify-between gap-2">
            <span className="truncate">{f.name}</span>
            <span className="text-muted-foreground truncate">{f.type ?? ""}</span>
          </div>
        ))}
        {data.fields.length > 10 && (
          <div className="text-muted-foreground">+{data.fields.length - 10} more</div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
}

const nodeTypes = { record: RecordCard };
const key = (s: string) => s.trim().toLowerCase();

export function EntityMap({ entities }: { entities: Board["entities"] }) {
  const { nodes, edges } = useMemo(() => {
    const known = new Map(entities.map((e) => [key(e.name), e.name]));
    const nodes: Node<CardData>[] = entities.map((e) => ({
      id: key(e.name), type: "record", position: { x: 0, y: 0 },
      data: { name: e.name, fields: e.fields ?? [] },
    }));
    const edges: Edge[] = entities.flatMap((e) =>
      (e.links ?? []).filter((l) => known.has(key(l.to))).map((l, i) => ({
        id: `${key(e.name)}-${key(l.to)}-${i}`, source: key(e.name), target: key(l.to),
        label: l.kind === "many" ? "many" : "one",
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { strokeDasharray: l.kind === "many" ? "4 3" : undefined },
      })));
    return { nodes, edges };
  }, [entities]);

  const [placed, setPlaced] = useState<Node<CardData>[]>([]);
  useEffect(() => {
    let gone = false;
    (async () => {
      const mod = await import("dagre");
      const dagre = (mod as any).default ?? mod;
      const g = new dagre.graphlib.Graph();
      g.setDefaultEdgeLabel(() => ({}));
      g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 70, marginx: 20, marginy: 20 });
      for (const n of nodes) g.setNode(n.id, { width: W, height: height(n.data) });
      for (const e of edges) g.setEdge(e.source, e.target);
      dagre.layout(g);
      if (gone) return;
      setPlaced(nodes.map((n) => {
        const p = g.node(n.id);
        return { ...n, position: { x: p.x - W / 2, y: p.y - height(n.data) / 2 } };
      }));
    })();
    return () => { gone = true; };
  }, [nodes, edges]);

  if (!entities.length) {
    return <p className="text-sm text-muted-foreground p-4">No records on the board yet.</p>;
  }
  return (
    <div className="h-[520px] rounded-lg border">
      <ReactFlow key={placed.map((n) => `${n.id}@${n.position.x},${n.position.y}`).join("|")} nodes={placed} edges={edges} nodeTypes={nodeTypes} fitView proOptions={{ hideAttribution: true }}
        nodesDraggable={false} nodesConnectable={false}>
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
