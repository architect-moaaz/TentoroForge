"use client";

/**
 * The App Flow view: the paths people take through the application, drawn.
 *
 * Every flow on one map of screens — a box per screen (or the tab or panel of
 * one), an arrow per move, labelled with what the person does there — so where
 * paths meet and where one ends is visible at once. Choosing a flow lights its
 * path. Read from `GET /api/projects/{id}/flows` (`app_flows.graph`).
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow, Background, Controls, Handle, Position, MarkerType,
  type Node, type Edge, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, CheckCircle2, LayoutPanelLeft, Monitor, PanelRight, Route, SquareStack } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type FlowNode = { id: string; page: string; screen: string; route: string; part: string; placement: string; last: boolean;
                  does?: string; process?: string };
type FlowEdge = { from: string; to: string; does: string; process: string; then: "go" | "offer" | "menu" };
type Flow = { id: string; name: string; role: string; goal: string; ends: string; nodes: FlowNode[]; edges: FlowEdge[] };
type FlowsResponse = { flows: Flow[]; findings: string[] };

const NODE_W = 230;
const NODE_H = 96;

/** One box per place: the screen, or the tab or panel of it. */
const placeKey = (n: FlowNode) => `${n.page}#${n.part}`;

type PlaceData = { screen: string; route: string; part: string; placement: string; ends: boolean; lit: boolean; dim: boolean;
                   finally: string[] };

function PlaceNode({ data }: NodeProps<Node<PlaceData>>) {
  const Icon = data.placement === "panel" ? PanelRight : data.placement === "tab" ? SquareStack
    : data.placement === "dialog" ? LayoutPanelLeft : Monitor;
  return (
    <div
      className={cn(
        "rounded-xl border px-3 py-2 shadow-sm transition-opacity",
        data.ends
          ? "border-emerald-300 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950"
          : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900",
        data.lit && "ring-2 ring-orange-400",
        data.dim && "opacity-35",
      )}
      style={{ width: NODE_W }}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <div className="flex items-center gap-2">
        {data.ends ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
          : <Icon className="h-4 w-4 shrink-0 text-orange-600" />}
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{data.screen}</div>
          {data.part && (
            <div className="truncate text-xs text-slate-600 dark:text-slate-300">
              {data.part} <span className="text-slate-400">· {data.placement}</span>
            </div>
          )}
          <div className="truncate font-mono text-[10px] text-slate-400">{data.route}</div>
        </div>
      </div>
      {/* What is done where a flow ends — often the work itself. */}
      {data.finally.slice(0, 2).map((f) => (
        <div key={f} className="mt-1.5 truncate rounded-md bg-orange-500 px-2 py-0.5 text-[11px] font-medium text-white"
             title={f}>
          {f}
        </div>
      ))}
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
}

const nodeTypes = { place: PlaceNode };

async function layout(nodes: Node<PlaceData>[], edges: Edge[]): Promise<Node<PlaceData>[]> {
  const dagreModule = await import("dagre");
  const dagre = (dagreModule as any).default ?? dagreModule;
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 60, ranksep: 90, marginx: 30, marginy: 30 });
  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 } };
  });
}

export function AppFlowPanel({ projectId }: { projectId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["project", projectId, "flows"],
    queryFn: () => api.get<FlowsResponse>(`/api/projects/${projectId}/flows`),
    retry: false,
  });
  const [chosen, setChosen] = useState<string | null>(null);
  const [placed, setPlaced] = useState<Node<PlaceData>[]>([]);

  // The map: every flow's places merged, every move an arrow.
  const { rawNodes, rawEdges } = useMemo(() => {
    // One flow chosen is drawn alone, like a flow diagram; all of them make
    // the map, where paths meet.
    const flows = (data?.flows ?? []).filter((f) => chosen === null || f.id === chosen);
    const places = new Map<string, Node<PlaceData>>();
    const lit = new Set<string>();
    const edges: Edge[] = [];
    for (const f of flows) {
      const keyOf = new Map(f.nodes.map((n) => [n.id, placeKey(n)]));
      for (const n of f.nodes) {
        const k = placeKey(n);
        const was = places.get(k);
        // Only a process done where a flow ends is drawn in its box; a last
        // step that only looks ("sees the order") is the end itself.
        const action = n.last && n.process ? n.process : "";
        const showAction = action && (chosen === null || chosen === f.id);
        places.set(k, {
          id: k, type: "place", position: { x: 0, y: 0 },
          data: { screen: n.screen, route: n.route, part: n.part, placement: n.placement,
                  ends: (was?.data.ends ?? false) || (n.last && !action),
                  lit: false, dim: false,
                  finally: [...new Set([...(was?.data.finally ?? []), ...(showAction ? [action] : [])])] },
        });
        if (chosen === f.id) lit.add(k);
      }
      f.edges.forEach((e, i) => {
        const on = chosen === null || chosen === f.id;
        // The process when one runs, else what they do — short enough to read.
        const said = e.process || e.does;
        const label = said.length > 34 ? `${said.slice(0, 32).trimEnd()}…` : said;
        edges.push({
          id: `${f.id}-${i}`,
          source: keyOf.get(e.from)!, target: keyOf.get(e.to)!,
          label: label || undefined,
          animated: chosen === f.id,
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          style: {
            strokeWidth: chosen === f.id ? 2.5 : 1.5,
            stroke: chosen === f.id ? "#ea580c" : "#94a3b8",
            strokeDasharray: e.then === "offer" ? "6 4" : e.then === "menu" ? "2 4" : undefined,
            opacity: on ? 1 : 0.2,
          },
          labelStyle: { fontSize: 11, fill: "#334155" },
          labelBgStyle: { fill: "#fff" },
          labelBgPadding: [4, 2],
          labelBgBorderRadius: 4,
        });
      });
    }
    const nodes = [...places.values()].map((n) => ({
      ...n, data: { ...n.data, lit: lit.has(n.id), dim: chosen !== null && !lit.has(n.id) },
    }));
    return { rawNodes: nodes, rawEdges: edges };
  }, [data, chosen]);

  useEffect(() => {
    let live = true;
    void layout(rawNodes, rawEdges).then((n) => { if (live) setPlaced(n); });
    return () => { live = false; };
  }, [rawNodes, rawEdges]);

  if (isLoading) return <div className="p-6 text-sm text-muted-foreground">Reading the application's flows…</div>;
  if (error) return <div className="p-6 text-sm text-muted-foreground">This project has no definition yet.</div>;
  const flows = data?.flows ?? [];
  if (!flows.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <Route className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm font-medium">No app flow yet</p>
        <p className="max-w-md text-sm text-muted-foreground">
          The paths people take through this application are written when it is built. For an application
          built before that, ask Smith to &ldquo;write the app flow&rdquo;.
        </p>
      </div>
    );
  }
  const current = flows.find((f) => f.id === chosen);
  const byRole = flows.reduce<Record<string, Flow[]>>((acc, f) => {
    (acc[f.role || "Everyone"] ??= []).push(f);
    return acc;
  }, {});

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div className="mb-2 flex items-center gap-2">
          <Route className="h-4 w-4 text-orange-600" />
          <h2 className="text-sm font-semibold">App Flow</h2>
          <span className="text-xs text-muted-foreground">
            {flows.length} flow{flows.length === 1 ? "" : "s"} · solid: taken there · dashed: shown the way · dotted: by the menu
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setChosen(null)}
            className={cn("rounded-full border px-3 py-1 text-xs",
              chosen === null ? "border-orange-400 bg-orange-50 text-orange-700 dark:bg-orange-950"
                : "border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300")}
          >
            All flows
          </button>
          {Object.entries(byRole).map(([role, list]) => (
            <div key={role} className="flex flex-wrap items-center gap-1">
              <span className="text-xs font-medium text-slate-500">{role}:</span>
              {list.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setChosen(chosen === f.id ? null : f.id)}
                  className={cn("rounded-full border px-3 py-1 text-xs",
                    chosen === f.id ? "border-orange-400 bg-orange-50 text-orange-700 dark:bg-orange-950"
                      : "border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300")}
                >
                  {f.name}
                </button>
              ))}
            </div>
          ))}
        </div>
        {current && (
          <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">
            <span className="font-medium">{current.goal}</span>
            {current.ends && <> — ends: {current.ends}</>}
          </p>
        )}
      </div>
      <div className="min-h-0 flex-1">
        {/* Mounted once laid out, so `fitView` frames the real positions. */}
        {placed.length > 0 && (
        <ReactFlow key={`${chosen ?? "all"}-${placed.length}`} nodes={placed} edges={rawEdges} nodeTypes={nodeTypes}
                   fitView fitViewOptions={{ padding: 0.15 }} minZoom={0.2}
                   nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}>
          <Background gap={20} />
          <Controls showInteractive={false} />
        </ReactFlow>
        )}
      </div>
      {!!data?.findings?.length && (
        <div className="max-h-32 overflow-auto border-t border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {data.findings.map((f, i) => (
            <div key={i} className="flex gap-2"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{f}</div>
          ))}
        </div>
      )}
    </div>
  );
}

export default AppFlowPanel;
