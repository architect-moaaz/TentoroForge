"use client";

/**
 * The App Flow view: the paths people take through the application, drawn.
 *
 * Every flow on one map of screens — a card per screen (or the tab or panel of
 * one), a curved arrow per move, labelled with the process or what the person
 * does — so where paths meet and where each ends is visible at once. Choosing
 * a flow draws it alone, numbered, with its story across the top. Each person
 * has a colour, and it follows their paths everywhere. Read from
 * `GET /api/projects/{id}/flows` (`app_flows.graph`).
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow, Background, BackgroundVariant, Controls, Handle, Position, MarkerType,
  BaseEdge, EdgeLabelRenderer, getSmoothStepPath,
  type Node, type Edge, type NodeProps, type EdgeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle, AppWindow, ArrowRight, CheckCircle2, ChevronRight, Flag, Map as MapIcon, Monitor,
  PanelRight, Route, SquareStack, Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

// --------------------------------------------------------------------------
// The shape `app_flows.graph` returns
// --------------------------------------------------------------------------

import type { Flow, FlowNode, FlowsResponse } from "@/lib/appFlows";
import { useAppFlowStore } from "@/stores/appFlow";

// --------------------------------------------------------------------------
// A colour per person
// --------------------------------------------------------------------------

export type Hue = { stroke: string; soft: string; badge: string; ring: string; text: string; bar: string };
export const HUES: Hue[] = [
  { stroke: "#f97316", soft: "bg-orange-50 dark:bg-orange-950/40", badge: "bg-gradient-to-br from-orange-400 to-rose-500",
    ring: "ring-orange-400/70", text: "text-orange-600 dark:text-orange-400", bar: "from-orange-400 to-rose-500" },
  { stroke: "#6366f1", soft: "bg-indigo-50 dark:bg-indigo-950/40", badge: "bg-gradient-to-br from-indigo-400 to-violet-600",
    ring: "ring-indigo-400/70", text: "text-indigo-600 dark:text-indigo-400", bar: "from-indigo-400 to-violet-600" },
  { stroke: "#10b981", soft: "bg-emerald-50 dark:bg-emerald-950/40", badge: "bg-gradient-to-br from-emerald-400 to-teal-600",
    ring: "ring-emerald-400/70", text: "text-emerald-600 dark:text-emerald-400", bar: "from-emerald-400 to-teal-600" },
  { stroke: "#0ea5e9", soft: "bg-sky-50 dark:bg-sky-950/40", badge: "bg-gradient-to-br from-sky-400 to-blue-600",
    ring: "ring-sky-400/70", text: "text-sky-600 dark:text-sky-400", bar: "from-sky-400 to-blue-600" },
  { stroke: "#d946ef", soft: "bg-fuchsia-50 dark:bg-fuchsia-950/40", badge: "bg-gradient-to-br from-fuchsia-400 to-pink-600",
    ring: "ring-fuchsia-400/70", text: "text-fuchsia-600 dark:text-fuchsia-400", bar: "from-fuchsia-400 to-pink-600" },
];

const placeKey = (n: FlowNode) => `${n.page}#${n.part}`;
const short = (s: string, n = 30) => (s.length > n ? `${s.slice(0, n - 2).trimEnd()}…` : s);
const initials = (s: string) =>
  s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

function placementIcon(placement: string) {
  return placement === "panel" ? PanelRight : placement === "tab" ? SquareStack
    : placement === "dialog" ? AppWindow : Monitor;
}

// --------------------------------------------------------------------------
// A screen card
// --------------------------------------------------------------------------

const NODE_W = 264;
const NODE_H = 112;

type PlaceData = {
  screen: string; route: string; part: string; placement: string;
  ends: boolean; actions: string[]; step: number | null; hue: Hue | null; start: boolean;
};

function PlaceNode({ data }: NodeProps<Node<PlaceData>>) {
  const Icon = placementIcon(data.placement);
  const hue = data.hue;
  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-2xl border bg-white/95 shadow-[0_8px_24px_-12px_rgba(15,23,42,0.28)]",
        "backdrop-blur transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_16px_34px_-14px_rgba(15,23,42,0.4)]",
        "dark:bg-slate-900/95 dark:shadow-black/40",
        data.ends ? "border-emerald-300/80 dark:border-emerald-700" : "border-slate-200/80 dark:border-slate-700/80",
      )}
      style={{ width: NODE_W }}
    >
      {/* The accent: the person's colour, or the end's green. */}
      <div className={cn("h-1 w-full bg-gradient-to-r",
        data.ends ? "from-emerald-400 to-teal-500"
          : hue ? hue.bar : "from-slate-200 to-slate-300 dark:from-slate-700 dark:to-slate-600")} />
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-transparent" />
      <div className="flex gap-3 px-3.5 pb-3 pt-2.5">
        <div className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
          data.ends ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/60 dark:text-emerald-300"
            : hue ? cn(hue.soft, hue.text) : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300",
        )}>
          {data.ends ? <CheckCircle2 className="h-[18px] w-[18px]" /> : <Icon className="h-[18px] w-[18px]" />}
        </div>
        <div className="min-w-0 flex-1 pr-6">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13px] font-semibold tracking-tight text-slate-900 dark:text-slate-50">
              {data.screen}
            </span>
            {data.start && (
              <span className="rounded-full bg-slate-900 px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider text-white dark:bg-white dark:text-slate-900">
                start
              </span>
            )}
          </div>
          {data.part && (
            <div className="mt-0.5 flex items-center gap-1 text-[11px] text-slate-600 dark:text-slate-300">
              <span className="truncate">{data.part}</span>
              <span className="rounded bg-slate-100 px-1 py-px text-[9px] uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                {data.placement}
              </span>
            </div>
          )}
          <div className="mt-0.5 truncate font-mono text-[10px] text-slate-400 dark:text-slate-500">{data.route}</div>
        </div>
      </div>
      {data.actions.length > 0 && (
        <div className="flex flex-wrap gap-1 px-3.5 pb-3">
          {data.actions.slice(0, 2).map((a) => (
            <span key={a} title={a}
              className="inline-flex max-w-full items-center gap-1 truncate rounded-full bg-gradient-to-r from-orange-500 to-rose-500 px-2 py-0.5 text-[10.5px] font-medium text-white shadow-sm">
              <Zap className="h-3 w-3 shrink-0" />{short(a, 28)}
            </span>
          ))}
        </div>
      )}
      {data.step !== null && (
        <div className={cn(
          "absolute right-2 top-3 flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 text-[11px] font-bold text-white shadow-md",
          data.ends ? "bg-gradient-to-br from-emerald-400 to-teal-600" : hue?.badge ?? "bg-slate-500",
        )}>
          {data.step}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-transparent" />
    </div>
  );
}

// --------------------------------------------------------------------------
// A move between screens
// --------------------------------------------------------------------------

type MoveData = { label: string; process: boolean; then: "go" | "offer" | "menu"; color: string; lit: boolean };

function MoveEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }:
  EdgeProps<Edge<MoveData>>) {
  const [path, lx, ly] = getSmoothStepPath({
    sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 18, offset: 22,
  });
  const d = data!;
  const dash = d.then === "offer" ? "7 5" : d.then === "menu" ? "2 6" : undefined;
  return (
    <>
      {d.lit && (
        <BaseEdge id={`${id}-glow`} path={path}
          style={{ stroke: d.color, strokeWidth: 10, opacity: 0.12 }} />
      )}
      <BaseEdge id={id} path={path} markerEnd={markerEnd}
        style={{
          stroke: d.color, strokeWidth: d.lit ? 2.6 : 1.6,
          strokeDasharray: dash ?? (d.lit ? "8 6" : undefined),
          animation: d.lit ? "appflow-dash 1.1s linear infinite" : undefined,
          opacity: d.lit ? 1 : 0.8,
        }} />
      {d.label && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan pointer-events-auto absolute flex items-center gap-1 rounded-full border border-white/70 bg-white/90 px-2 py-0.5 text-[10.5px] font-medium text-slate-700 shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/90 dark:text-slate-200"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
            title={d.label}
          >
            {d.process ? <Zap className="h-3 w-3" style={{ color: d.color }} />
              : <span className="h-1.5 w-1.5 rounded-full" style={{ background: d.color }} />}
            {short(d.label, 30)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { place: PlaceNode };
const edgeTypes = { move: MoveEdge };

async function layout(nodes: Node<PlaceData>[], edges: Edge[]): Promise<Node<PlaceData>[]> {
  const dagreModule = await import("dagre");
  const dagre = (dagreModule as any).default ?? dagreModule;
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 70, ranksep: 110, marginx: 40, marginy: 40 });
  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 } };
  });
}

// --------------------------------------------------------------------------
// The drawing
// --------------------------------------------------------------------------

/** The people a set of flows is for, in order: each person's colour is their place here. */
export function rolesOf(flows: Flow[]): string[] {
  return [...new Set(flows.map((f) => f.role || "Everyone"))];
}

export function hueFor(roles: string[], role: string): Hue {
  return HUES[Math.max(0, roles.indexOf(role || "Everyone")) % HUES.length];
}

/**
 * The drawing itself: every flow on one map, or one flow alone when `chosen`
 * names it — shared by the App Flow tab and Smith's side panel. `compact`
 * leaves out the zoom controls, for a panel a third of the screen wide.
 */
export function FlowCanvas({ flows: allFlows, chosen, compact = false }:
  { flows: Flow[]; chosen: string | null; compact?: boolean }) {
  const roles = useMemo(() => rolesOf(allFlows), [allFlows]);
  const [placed, setPlaced] = useState<Node<PlaceData>[]>([]);
  const { rawNodes, rawEdges } = useMemo(() => {
    const flows = allFlows.filter((f) => chosen === null || f.id === chosen);
    const places = new Map<string, Node<PlaceData>>();
    const edges: Edge<MoveData>[] = [];
    for (const f of flows) {
      const hue = HUES[Math.max(0, roles.indexOf(f.role || "Everyone")) % HUES.length];
      const keyOf = new Map(f.nodes.map((n) => [n.id, placeKey(n)]));
      f.nodes.forEach((n, i) => {
        const k = placeKey(n);
        const was = places.get(k);
        const action = n.last && n.process ? n.process : "";
        places.set(k, {
          id: k, type: "place", position: { x: 0, y: 0 },
          data: {
            screen: n.screen, route: n.route, part: n.part, placement: n.placement,
            ends: (was?.data.ends ?? false) || (n.last && !action),
            actions: [...new Set([...(was?.data.actions ?? []), ...(action ? [action] : [])])],
            step: chosen ? i + 1 : null,
            // A screen two people share takes no one's colour on the map.
            hue: was && was.data.hue !== hue ? null : hue,
            start: (was?.data.start ?? false) || i === 0,
          },
        });
      });
      f.edges.forEach((e, i) => {
        edges.push({
          id: `${f.id}-${i}`, type: "move",
          source: keyOf.get(e.from)!, target: keyOf.get(e.to)!,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: hue.stroke },
          data: { label: e.process || e.does, process: !!e.process, then: e.then, color: hue.stroke, lit: !!chosen },
        });
      });
    }
    return { rawNodes: [...places.values()], rawEdges: edges };
  }, [allFlows, roles, chosen]);

  useEffect(() => {
    let live = true;
    void layout(rawNodes, rawEdges).then((n) => { if (live) setPlaced(n); });
    return () => { live = false; };
  }, [rawNodes, rawEdges]);

  return (
    <>
      <style>{`@keyframes appflow-dash { to { stroke-dashoffset: -28; } }`}</style>
      {placed.length > 0 && (
        <ReactFlow key={`${chosen ?? "all"}-${placed.length}`} nodes={placed} edges={rawEdges}
          nodeTypes={nodeTypes} edgeTypes={edgeTypes}
          fitView fitViewOptions={{ padding: compact ? 0.1 : 0.18, duration: 400 }} minZoom={0.1} maxZoom={1.6}
          nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}
          zoomOnScroll={!compact} panOnScroll={compact}>
          <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#cbd5e1" />
          {!compact && (
            <Controls showInteractive={false}
              className="!overflow-hidden !rounded-xl !border !border-slate-200 !shadow-sm dark:!border-slate-700" />
          )}
        </ReactFlow>
      )}
    </>
  );
}

// --------------------------------------------------------------------------
// The panel
// --------------------------------------------------------------------------

export function AppFlowPanel({ projectId }: { projectId: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["project", projectId, "flows"],
    queryFn: () => api.get<FlowsResponse>(`/api/projects/${projectId}/flows`),
    retry: false,
  });
  const focus = useAppFlowStore((st) => st.focus);
  const requested = useAppFlowStore((st) => st.requested);
  const [chosen, setChosen] = useState<string | null>(focus);
  // "Show me this path" from Smith's side panel.
  useEffect(() => { if (requested) setChosen(focus); }, [requested, focus]);
  const [showFindings, setShowFindings] = useState(true);

  const allFlows = useMemo(() => data?.flows ?? [], [data]);
  const roles = useMemo(() => rolesOf(allFlows), [allFlows]);
  const hueOf = (role: string) => hueFor(roles, role);
  const current = allFlows.find((f) => f.id === chosen) ?? null;

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
        <Route className="h-4 w-4 animate-pulse text-orange-500" /> Tracing the paths through your application…
      </div>
    );
  }
  if (error) return <div className="p-6 text-sm text-muted-foreground">This project has no definition yet.</div>;
  if (!allFlows.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-gradient-to-b from-orange-50/60 to-transparent p-6 text-center dark:from-orange-950/20">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-orange-400 to-rose-500 text-white shadow-lg">
          <Route className="h-7 w-7" />
        </div>
        <p className="text-base font-semibold">No app flow yet</p>
        <p className="max-w-md text-sm text-muted-foreground">
          The paths people take through this application are written when it is built. For an application
          built before that, ask Smith to &ldquo;write the app flow&rdquo;.
        </p>
      </div>
    );
  }

  const byRole = roles.map((role) => ({
    role, hue: hueOf(role), flows: allFlows.filter((f) => (f.role || "Everyone") === role),
  }));

  return (
    <div className="flex h-full min-h-0 bg-slate-50/60 dark:bg-slate-950">

      {/* The flows, by person */}
      <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200/80 bg-white/80 backdrop-blur md:flex dark:border-slate-800 dark:bg-slate-900/70">
        <div className="border-b border-slate-200/80 px-4 py-4 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-orange-400 to-rose-500 text-white shadow-md">
              <Route className="h-[18px] w-[18px]" />
            </div>
            <div>
              <h2 className="text-sm font-semibold tracking-tight">App Flow</h2>
              <p className="text-[11px] text-muted-foreground">
                {allFlows.length} path{allFlows.length === 1 ? "" : "s"} · {roles.length} {roles.length === 1 ? "person" : "people"}
              </p>
            </div>
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
          <button type="button" onClick={() => setChosen(null)}
            className={cn("flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition",
              chosen === null
                ? "border-slate-900 bg-slate-900 text-white shadow-md dark:border-white dark:bg-white dark:text-slate-900"
                : "border-slate-200 bg-white hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900")}>
            <MapIcon className="h-4 w-4" />
            <div>
              <div className="text-[13px] font-semibold">The whole map</div>
              <div className={cn("text-[11px]", chosen === null ? "opacity-70" : "text-muted-foreground")}>
                Every path, and where they meet
              </div>
            </div>
          </button>
          {byRole.map(({ role, hue, flows }) => (
            <div key={role}>
              <div className="mb-1.5 flex items-center gap-2 px-1">
                <span className={cn("flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold text-white shadow-sm", hue.badge)}>
                  {initials(role)}
                </span>
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">{role}</span>
                <span className="text-[11px] text-muted-foreground">{flows.length}</span>
              </div>
              <div className="space-y-1.5">
                {flows.map((f) => (
                  <button key={f.id} type="button" onClick={() => setChosen(chosen === f.id ? null : f.id)}
                    className={cn("w-full rounded-xl border bg-white px-3 py-2 text-left transition dark:bg-slate-900",
                      chosen === f.id ? cn("border-transparent shadow-md ring-2", hue.ring)
                        : "border-slate-200/80 hover:-translate-y-px hover:border-slate-300 hover:shadow-sm dark:border-slate-800")}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[12.5px] font-semibold text-slate-800 dark:text-slate-100">{f.name}</span>
                      <ChevronRight className={cn("h-3.5 w-3.5 shrink-0", chosen === f.id ? hue.text : "text-slate-300")} />
                    </div>
                    {f.goal && <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{f.goal}</p>}
                    <div className="mt-1.5 flex items-center gap-1">
                      {f.nodes.map((n, i) => (
                        <span key={n.id} className="flex items-center gap-1">
                          <span className={cn("h-1.5 w-1.5 rounded-full", n.last && "bg-emerald-500")}
                            style={n.last ? undefined : { background: hue.stroke }} />
                          {i < f.nodes.length - 1 && <span className="h-px w-3 bg-slate-200 dark:bg-slate-700" />}
                        </span>
                      ))}
                      <span className="ml-1 text-[10px] text-muted-foreground">{f.nodes.length} steps</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </aside>

      {/* The canvas */}
      <section className="flex min-w-0 flex-1 flex-col">
        {/* Narrow panes: the flows as chips. */}
        <div className="flex gap-1.5 overflow-x-auto border-b border-slate-200/80 bg-white/80 px-3 py-2 md:hidden dark:border-slate-800 dark:bg-slate-900/70">
          <button type="button" onClick={() => setChosen(null)}
            className={cn("shrink-0 rounded-full border px-3 py-1 text-xs",
              chosen === null ? "border-slate-900 bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                : "border-slate-200 dark:border-slate-700")}>
            Whole map
          </button>
          {allFlows.map((f) => (
            <button key={f.id} type="button" onClick={() => setChosen(f.id)}
              className={cn("shrink-0 rounded-full border px-3 py-1 text-xs",
                chosen === f.id ? cn("border-transparent ring-2", hueOf(f.role).ring) : "border-slate-200 dark:border-slate-700")}>
              {f.name}
            </button>
          ))}
        </div>

        {/* The story of the chosen flow, step by step. */}
        {current ? (
          <div className="border-b border-slate-200/80 bg-white/80 px-5 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white", hueOf(current.role).badge)}>
                {current.role || "Everyone"}
              </span>
              <h3 className="text-[15px] font-semibold tracking-tight text-slate-900 dark:text-slate-50">{current.name}</h3>
              {current.goal && <span className="text-xs text-muted-foreground">— {current.goal}</span>}
            </div>
            <div className="mt-2.5 flex items-center gap-1.5 overflow-x-auto pb-0.5">
              {current.nodes.map((n, i) => (
                <div key={n.id} className="flex shrink-0 items-center gap-1.5">
                  <span className={cn("inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px]",
                    n.last ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200"
                      : "border-slate-200 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200")}>
                    <span className={cn("flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold text-white",
                      n.last ? "bg-emerald-500" : hueOf(current.role).badge)}>{i + 1}</span>
                    {n.screen}{n.part ? <span className="text-slate-400"> · {n.part}</span> : null}
                  </span>
                  {i < current.edges.length && (
                    <span className="flex items-center gap-1 text-[10.5px] text-muted-foreground">
                      <ArrowRight className="h-3 w-3" />
                      <span className="max-w-[160px] truncate">{current.edges[i].process || current.edges[i].does}</span>
                      <ArrowRight className="h-3 w-3" />
                    </span>
                  )}
                </div>
              ))}
            </div>
            {current.ends && (
              <p className="mt-2 flex items-start gap-1.5 text-[11.5px] text-emerald-700 dark:text-emerald-300">
                <Flag className="mt-0.5 h-3 w-3 shrink-0" />{current.ends}
              </p>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-between border-b border-slate-200/80 bg-white/80 px-5 py-2.5 backdrop-blur dark:border-slate-800 dark:bg-slate-900/70">
            <span className="text-xs text-muted-foreground">Choose a path to follow it step by step</span>
            <div className="hidden items-center gap-4 text-[11px] text-muted-foreground sm:flex">
              <span className="flex items-center gap-1.5"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#64748b" strokeWidth="2" /></svg>taken there</span>
              <span className="flex items-center gap-1.5"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#64748b" strokeWidth="2" strokeDasharray="5 3" /></svg>shown the way</span>
              <span className="flex items-center gap-1.5"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#64748b" strokeWidth="2" strokeDasharray="1.5 4" /></svg>by the menu</span>
            </div>
          </div>
        )}

        <div className="relative min-h-0 flex-1 bg-[radial-gradient(ellipse_at_top,rgba(251,146,60,0.09),transparent_60%)] dark:bg-[radial-gradient(ellipse_at_top,rgba(251,146,60,0.06),transparent_60%)]">
          <FlowCanvas flows={allFlows} chosen={chosen} />
        </div>

        {!!data?.findings?.length && (
          <div className="border-t border-amber-200 bg-amber-50/90 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
            <button type="button" onClick={() => setShowFindings((v) => !v)}
              className="flex w-full items-center gap-2 px-4 py-2 font-medium">
              <AlertTriangle className="h-3.5 w-3.5" />
              {data.findings.length} thing{data.findings.length === 1 ? "" : "s"} in the flows name what the app does not have
              <ChevronRight className={cn("ml-auto h-3.5 w-3.5 transition", showFindings && "rotate-90")} />
            </button>
            {showFindings && (
              <div className="max-h-28 space-y-1 overflow-auto px-4 pb-2">
                {data.findings.map((f, i) => <div key={i}>• {f}</div>)}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

export default AppFlowPanel;
