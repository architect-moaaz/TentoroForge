"use client";

// The Rules Map — one record's rules as a decision diagram, drawn the way DMN
// draws a Decision Requirements Diagram: the fields a rule reads on the left,
// the rules and tables in the middle, what they write, refuse or hint on the
// right, and the workflows they run in. "Play a save" runs a record through
// the app's own engine and lights the path it took, rule by rule, in order.
//
// Motion: transform/opacity only, critically damped curves, staggered by the
// order the engine fired the rules; a cross-fade under reduced motion.

import { memo, useEffect, useMemo, useState } from "react";
import {
  Background, BackgroundVariant, Controls, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation } from "@tanstack/react-query";
import {
  Ban, Bell, CircleDot, GitBranch, Lightbulb, Loader2, PenLine, Play, RotateCcw, Scale, Table2, X,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { problemsOf } from "@/lib/blueprint-rules";
import { buildRuleGraph, lightUp, neighbourhood, type MapNode, type RuleState, type RunLight } from "@/lib/rules-graph";
import { coerceSample, humanField, type FiresOn, type StudioCatalogue, type StudioView, type TestAnswer } from "@/lib/rules-studio";
import { FieldInput } from "./TestPanel";

const STEP_MS = 160;            // the gap between one rule's light and the next

function useReducedMotion() {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    try {
      const m = window.matchMedia("(prefers-reduced-motion: reduce)");
      setReduce(m.matches);
      const on = () => setReduce(m.matches);
      m.addEventListener?.("change", on);
      return () => m.removeEventListener?.("change", on);
    } catch { /* no matchMedia: full motion */ }
  }, []);
  return reduce;
}

const show = (v: unknown) => (v === null || v === undefined || v === "" ? "blank" : typeof v === "string" ? v : JSON.stringify(v));

type Data = MapNode & Record<string, unknown> & {
  dim: boolean;
  state?: RuleState;
  step?: number;
  value?: unknown;
  hasValue?: boolean;
  lit?: boolean;
  delay: number;
  reduce: boolean;
  onOpen?: () => void;
};

const handles = (
  <>
    <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
    <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-transparent" />
  </>
);

/** Fades and settles a node; its run state comes in after its turn. */
const frame = (d: Data) => ({
  className: cn("transition-[opacity,transform,box-shadow,background-color,border-color] duration-300 ease-[cubic-bezier(.2,.8,.2,1)]",
                d.dim ? "opacity-20" : "opacity-100"),
  style: { transitionDelay: d.reduce ? "0ms" : `${d.delay}ms` },
});

function ValueChip({ d, tone }: { d: Data; tone: "sky" | "emerald" }) {
  if (!d.hasValue) return null;
  return (
    <span key={show(d.value)}
          className={cn("absolute -top-2.5 right-2 max-w-[150px] truncate rounded-full px-2 py-0.5 font-mono text-[10px] font-medium shadow-sm",
                        "motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-90 motion-safe:duration-300",
                        tone === "sky" ? "bg-sky-600 text-white" : "bg-emerald-600 text-white")}
          style={{ animationDelay: d.reduce ? "0ms" : `${d.delay}ms`, animationFillMode: "both" }}>
      {show(d.value)}
    </span>
  );
}

const FieldNode = memo(({ data }: NodeProps<Node<Data>>) => {
  const write = data.kind === "write";
  const f = frame(data);
  return (
    <div className={cn(f.className, "relative flex h-[52px] w-[176px] items-center gap-2 rounded-full border bg-background px-3 shadow-sm",
                       write ? "border-emerald-300 dark:border-emerald-800" : "border-sky-300 dark:border-sky-800",
                       data.lit && (write ? "border-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,.15)]" : "border-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,.15)]"))}
         style={f.style} data-map-node={data.id}>
      {handles}
      {write ? <PenLine className="h-3.5 w-3.5 shrink-0 text-emerald-600" /> : <CircleDot className="h-3.5 w-3.5 shrink-0 text-sky-600" />}
      <span className="min-w-0">
        <span className="block truncate text-xs font-medium">{data.label}</span>
        {data.detail && <span className="block truncate text-[10px] text-muted-foreground">{data.detail}</span>}
      </span>
      <ValueChip d={data} tone={write ? "emerald" : "sky"} />
    </div>
  );
});
FieldNode.displayName = "FieldNode";

const STATE_SAID: Record<RuleState, string> = {
  idle: "", held: "acted", missed: "otherwise", quiet: "did not fire", broken: "could not be read",
};

const RuleNode = memo(({ data }: NodeProps<Node<Data>>) => {
  const table = data.ruleKind === "decision_table";
  const f = frame(data);
  const s = data.state ?? "idle";
  return (
    <button type="button" onClick={data.onOpen} aria-label={`Open ${data.label}`}
            className={cn(f.className, "group relative flex h-[84px] w-[260px] overflow-hidden rounded-xl border bg-card text-left shadow-sm",
                          "hover:-translate-y-0.5 hover:shadow-md active:scale-[0.99]",
                          !data.enabled && "border-dashed",
                          s === "held" && "border-emerald-500 shadow-[0_0_0_5px_rgba(16,185,129,.16)]",
                          s === "missed" && "border-slate-400",
                          s === "quiet" && "opacity-40",
                          s === "broken" && "border-rose-500")}
            style={f.style} data-map-node={data.id} data-state={s}>
      {handles}
      <span className={cn("w-1.5 shrink-0", table ? "bg-indigo-500" : "bg-violet-500", !data.enabled && "opacity-40")} />
      <span className="flex min-w-0 flex-1 flex-col justify-center gap-0.5 px-3">
        <span className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {table ? <Table2 className="h-3 w-3 text-indigo-500" /> : <Scale className="h-3 w-3 text-violet-500" />}
          {table ? "Decision table" : "When → then"} · {data.detail}
          {!data.enabled && <span className="rounded bg-muted px-1 normal-case tracking-normal">off</span>}
        </span>
        <span className="line-clamp-2 text-[13px] font-semibold leading-snug">{data.label}</span>
        {s !== "idle" && (
          <span className={cn("text-[10px] font-medium", s === "held" ? "text-emerald-700 dark:text-emerald-400" : s === "broken" ? "text-rose-600" : "text-muted-foreground")}>
            {STATE_SAID[s]}
          </span>
        )}
      </span>
      {data.step !== undefined && s !== "quiet" && (
        <span className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-foreground text-[10px] font-semibold text-background motion-safe:animate-in motion-safe:zoom-in-50 motion-safe:duration-300"
              style={{ animationDelay: data.reduce ? "0ms" : `${data.delay}ms`, animationFillMode: "both" }}>
          {data.step + 1}
        </span>
      )}
    </button>
  );
});
RuleNode.displayName = "RuleNode";

const OutcomeNode = memo(({ data }: NodeProps<Node<Data>>) => {
  const f = frame(data);
  const tone = {
    refuse: { box: "border-rose-300 bg-rose-50/80 dark:border-rose-900 dark:bg-rose-950/40", icon: <Ban className="h-4 w-4 text-rose-600" />, lit: "border-rose-500 shadow-[0_0_0_5px_rgba(244,63,94,.18)]" },
    hint: { box: "border-amber-300 bg-amber-50/80 dark:border-amber-900 dark:bg-amber-950/30", icon: <Lightbulb className="h-4 w-4 text-amber-600" />, lit: "border-amber-500" },
    notify: { box: "border-sky-300 bg-sky-50/80 dark:border-sky-900 dark:bg-sky-950/30", icon: <Bell className="h-4 w-4 text-sky-600" />, lit: "border-sky-500" },
    workflow: { box: "border-violet-300 bg-violet-50/80 dark:border-violet-900 dark:bg-violet-950/30", icon: <GitBranch className="h-4 w-4 text-violet-600" />, lit: "border-violet-500" },
  }[data.kind as "refuse" | "hint" | "notify" | "workflow"];
  return (
    <div className={cn(f.className, "relative flex items-center gap-2 rounded-xl border px-3 shadow-sm", tone.box, data.lit && tone.lit,
                       data.kind === "refuse" ? "h-[60px] w-[230px]" : data.kind === "workflow" ? "h-[52px] w-[190px]" : "h-[52px] w-[200px]")}
         style={f.style} data-map-node={data.id}>
      {handles}
      {data.lit && data.kind === "refuse" && !data.reduce && (
        <span className="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-rose-500/60 motion-safe:animate-ping [animation-iteration-count:2]"
              style={{ animationDelay: `${data.delay}ms` }} />
      )}
      <span className="shrink-0">{tone.icon}</span>
      <span className="min-w-0">
        <span className="block truncate text-xs font-semibold">{data.label}</span>
        {data.detail && <span className="block truncate text-[10px] text-muted-foreground" title={data.detail}>{data.detail}</span>}
      </span>
    </div>
  );
});
OutcomeNode.displayName = "OutcomeNode";

const nodeTypes = { read: FieldNode, write: FieldNode, rule: RuleNode, refuse: OutcomeNode, hint: OutcomeNode, notify: OutcomeNode, workflow: OutcomeNode };

export function RulesMap(props: {
  projectId: string; views: StudioView[]; catalogue: StudioCatalogue | null; entityName: string | null;
  onOpen: (v: StudioView) => void;
}) {
  return <ReactFlowProvider><MapCanvas {...props} /></ReactFlowProvider>;
}

function MapCanvas({ projectId, views, catalogue, entityName, onOpen }: {
  projectId: string; views: StudioView[]; catalogue: StudioCatalogue | null; entityName: string | null;
  onOpen: (v: StudioView) => void;
}) {
  const reduce = useReducedMotion();
  const graph = useMemo(() => buildRuleGraph(views, catalogue, entityName), [views, catalogue, entityName]);
  const [hover, setHover] = useState<string | null>(null);
  const [light, setLight] = useState<RunLight | null>(null);
  const [answer, setAnswer] = useState<TestAnswer | null>(null);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { setLight(null); setAnswer(null); }, [entityName]);
  // The player docks beside the map; the map re-fits so no node hides behind it.
  const flow = useReactFlow();
  useEffect(() => {
    const t = setTimeout(() => flow.fitView({ padding: 0.18, duration: reduce ? 0 : 400 }), 60);
    return () => clearTimeout(t);
  }, [playing, flow, reduce]);

  const near = useMemo(() => (hover ? neighbourhood(graph, hover) : null), [graph, hover]);
  const ruleStep = useMemo(() => {
    const m = new Map<string, number>();
    (answer?.trace ?? []).forEach((t, i) => m.set(String(t.id), i));
    return m;
  }, [answer]);

  const nodes: Node<Data>[] = useMemo(() => graph.nodes.map((n) => {
    const ruleId = n.ruleId;
    const state = n.kind === "rule" && light ? light.rules.get(String(ruleId)) ?? "quiet" : undefined;
    const step = ruleId !== undefined ? ruleStep.get(String(ruleId)) : undefined;
    const incoming = graph.edges.filter((e) => e.target === n.id && light?.edges.has(e.id));
    const firstIn = incoming.length ? Math.min(...incoming.map((e) => light!.edges.get(e.id)!)) : undefined;
    const value = n.kind === "read" ? light?.values.get(n.field!) : n.kind === "write" ? light?.written.get(n.field!) : undefined;
    const hasValue = !!light && (n.kind === "read" ? light.values.has(n.field!) : n.kind === "write" ? light.written.has(n.field!) : false);
    const delay = !light ? 0 : n.kind === "read" ? 0 : n.kind === "rule" ? ((step ?? 0) + 1) * STEP_MS : ((firstIn ?? 0) + 1.6) * STEP_MS;
    const view = ruleId ? views.find((v) => String(v.rule.id) === String(ruleId)) : undefined;
    return {
      id: n.id, type: n.kind, position: { x: n.x, y: n.y }, draggable: false, selectable: false,
      data: { ...n, dim: !!near && !near.nodes.has(n.id), state, step, value, hasValue,
              lit: n.kind === "read" ? hasValue : incoming.length > 0, delay, reduce,
              onOpen: view ? () => onOpen(view) : undefined },
    };
  }), [graph, light, near, ruleStep, reduce, views, onOpen]);

  const edges: Edge[] = useMemo(() => graph.edges.map((e) => {
    const order = light?.edges.get(e.id);
    const carried = order !== undefined;
    const toRefuse = e.target.startsWith("refuse:");
    const color = carried ? (toRefuse ? "#e11d48" : "#059669")
      : e.branch === "otherwise" ? "#94a3b8" : e.target.startsWith("rule:") ? "#7dd3fc" : "#a5b4fc";
    const dim = (!!near && !near.edges.has(e.id)) || (!!light && !carried);
    return {
      id: e.id, source: e.source, target: e.target, type: "smoothstep", label: e.label,
      animated: carried && !reduce,
      labelStyle: { fontSize: 10, fill: "currentColor" },
      labelBgStyle: { fill: "var(--background)", fillOpacity: 0.85 },
      labelBgPadding: [4, 2] as [number, number],
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
      style: {
        stroke: color, strokeWidth: carried ? 2.25 : 1.25, strokeDasharray: e.branch === "otherwise" && !carried ? "4 3" : undefined,
        opacity: dim ? 0.15 : 1,
        transition: `opacity 300ms cubic-bezier(.2,.8,.2,1) ${reduce || !carried ? 0 : ((order ?? 0) + 1) * STEP_MS}ms, stroke 300ms`,
      },
    };
  }), [graph, light, near, reduce]);

  const ent = catalogue?.entities.find((x) => x.name === entityName);
  if (!graph.nodes.some((n) => n.kind === "rule")) {
    return (
      <div className="mx-auto mt-10 max-w-md rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground" data-testid="rules-map-empty">
        No rule checks {entityName ? `a ${entityName}` : "a record"} yet — the map draws the ones the app enforces.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[520px] gap-3">
    <div className="relative min-w-0 flex-1 overflow-hidden rounded-xl border bg-gradient-to-br from-slate-50 via-background to-violet-50/40 dark:from-slate-950 dark:via-background dark:to-violet-950/20"
         data-testid="rules-map">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.18 }}
                 minZoom={0.25} maxZoom={1.6} nodesConnectable={false} proOptions={{ hideAttribution: true }}
                 onNodeMouseEnter={(_, n) => setHover(n.id)} onNodeMouseLeave={() => setHover(null)}>
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} className="opacity-60" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      <Legend />
      {ent && !playing && (
        <Button onClick={() => setPlaying(true)} className="absolute bottom-4 left-4 shadow-lg active:scale-[0.97]" data-testid="play-a-save">
          <Play className="mr-1.5 h-4 w-4" /> Play a save
        </Button>
      )}
    </div>
    {ent && playing && (
      <PlayBar projectId={projectId} entity={ent} catalogue={catalogue} answer={answer}
               onClose={() => { setPlaying(false); setAnswer(null); setLight(null); }}
               onAnswer={(a) => { setAnswer(a); setLight(a && a.trace ? lightUp(graph, views, a) : null); }} />
    )}
    </div>
  );
}

function Legend() {
  const dot = "h-2 w-2 rounded-full";
  return (
    <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-3 rounded-full border bg-background/80 px-3 py-1.5 text-[11px] text-muted-foreground shadow-sm backdrop-blur">
      <span className="flex items-center gap-1.5"><span className={cn(dot, "bg-sky-500")} />reads</span>
      <span className="flex items-center gap-1.5"><span className={cn(dot, "bg-violet-500")} />rule</span>
      <span className="flex items-center gap-1.5"><span className={cn(dot, "bg-indigo-500")} />table</span>
      <span className="flex items-center gap-1.5"><span className={cn(dot, "bg-emerald-500")} />writes</span>
      <span className="flex items-center gap-1.5"><span className={cn(dot, "bg-rose-500")} />refuses</span>
      <span className="flex items-center gap-1.5"><span className={cn(dot, "bg-amber-500")} />form hint</span>
    </div>
  );
}

function PlayBar({ projectId, entity, catalogue, answer, onAnswer, onClose }: {
  projectId: string; entity: StudioCatalogue["entities"][number]; catalogue: StudioCatalogue | null;
  answer: TestAnswer | null; onAnswer: (a: TestAnswer | null) => void; onClose: () => void;
}) {
  const [event, setEvent] = useState<FiresOn>("create");
  const [now, setNow] = useState<Record<string, string>>({});
  const [before, setBefore] = useState<Record<string, string>>({});
  const fields = entity.fields.filter((f) => !["id", "createdAt", "updatedAt"].includes(f.name));
  const record = (vals: Record<string, string>) =>
    Object.fromEntries(fields.filter((f) => (vals[f.name] ?? "") !== "")
      .map((f) => [f.name, coerceSample(vals[f.name], f.type === "enum" ? "string" : f.type)]));
  const run = useMutation({
    mutationFn: () => api.post<TestAnswer>(`/api/projects/${projectId}/business-rules/test`, {
      entity: entity.id, event, record: record(now), previous: event === "update" ? record(before) : null,
    }),
    onSuccess: (r) => onAnswer(r),
    onError: (e) => onAnswer({ ok: false, problems: problemsOf(e) }),
  });
  void catalogue;

  const said = answer && (answer.problems?.length ? answer.problems[0]
    : answer.refused ? `Refused — “${(answer.errors ?? [])[0] ?? ""}”`
    : `Saved — ${Object.keys(answer.patches ?? {}).length} value${Object.keys(answer.patches ?? {}).length === 1 ? "" : "s"} set by the rules`);
  return (
    <aside className="flex w-[320px] shrink-0 flex-col rounded-xl border bg-background p-3 shadow-sm motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-right-4 motion-safe:duration-300"
           data-testid="play-bar">
      <div className="mb-2 flex items-center gap-2">
        <Play className="h-4 w-4 text-violet-600" />
        <p className="flex-1 text-sm font-semibold">Play a save of a {entity.name}</p>
        <button type="button" onClick={onClose} aria-label="Close the player" className="text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div role="radiogroup" aria-label="Which save" className="mb-2 inline-flex rounded-lg border p-0.5 text-xs">
        {(["create", "update"] as FiresOn[]).map((e) => (
          <button key={e} type="button" role="radio" aria-checked={event === e} onClick={() => setEvent(e)}
                  className={cn("rounded-md px-2.5 py-1 transition-colors", event === e ? "bg-primary text-primary-foreground" : "hover:bg-muted")}>
            {e === "create" ? "A new one" : "A change"}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
        {fields.map((f) => (
          <div key={f.name} className={cn("grid items-center gap-1.5", event === "update" ? "grid-cols-[88px_1fr_1fr]" : "grid-cols-[88px_1fr]")}>
            <span className="truncate text-[11px] text-muted-foreground" title={f.name}>{humanField(f.name)}</span>
            {event === "update" && <FieldInput f={f} label={`${f.name} before`} value={before[f.name] ?? ""} onChange={(v) => setBefore({ ...before, [f.name]: v })} />}
            <FieldInput f={f} label={`${f.name}${event === "update" ? " now" : ""}`} value={now[f.name] ?? ""} onChange={(v) => setNow({ ...now, [f.name]: v })} />
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Button size="sm" className="flex-1" onClick={() => run.mutate()} disabled={run.isPending} data-testid="play-run">
          {run.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />} Play it
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { setNow({}); setBefore({}); onAnswer(null); }} aria-label="Start again">
          <RotateCcw className="h-3.5 w-3.5" />
        </Button>
      </div>
      {said && (
        <p key={said} className={cn("mt-2 rounded-lg px-2.5 py-1.5 text-xs motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300",
                                    answer?.problems?.length || answer?.refused ? "bg-rose-50 text-rose-800 dark:bg-rose-950/40 dark:text-rose-200" : "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200")}
           data-testid="play-said">
          {said}
        </p>
      )}
    </aside>
  );
}
