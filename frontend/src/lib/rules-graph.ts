/**
 * The Rules Map: one record's rules as a decision diagram, the way DMN draws
 * a Decision Requirements Diagram — what each rule reads, what it decides,
 * and where that goes.
 *
 *   fields it reads  →  rules and tables  →  what they write / refuse / hint  →  workflows
 *
 * Pure: built from the studio's views and catalogue, laid out by dagre, and
 * lit by a test run's trace (`lightUp`). The canvas only draws it.
 */
import dagre from "dagre";
import type { StudioCatalogue, StudioView, TestAnswer } from "@/lib/rules-studio";
import { humanField } from "@/lib/rules-studio";

export type MapNodeKind = "read" | "rule" | "write" | "refuse" | "hint" | "notify" | "workflow";
export type Branch = "then" | "otherwise" | "table" | "always";

export interface MapNode {
  id: string;
  kind: MapNodeKind;
  label: string;
  /** Small second line: a field's type, a rule's sentence, a refusal's message. */
  detail?: string;
  ruleId?: string;
  ruleKind?: StudioView["kind"];
  enabled?: boolean;
  field?: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MapEdge {
  id: string;
  source: string;
  target: string;
  /** Which way out of the rule this is: its then, its otherwise, a table's outputs, or a read. */
  branch: Branch;
  ruleId: string;
  label?: string;
}

export interface RuleGraph {
  nodes: MapNode[];
  edges: MapEdge[];
}

const SIZE: Record<MapNodeKind, [number, number]> = {
  read: [176, 52], rule: [260, 84], write: [176, 52], refuse: [230, 60], hint: [200, 52], notify: [200, 52], workflow: [190, 52],
};

const FEEL_WORDS = new Set(["and", "or", "not", "true", "false", "null", "in", "between", "if", "then", "else",
  "user", "previous", "date", "time", "today", "now", "duration", "count", "sum", "min", "max", "string", "length",
  "contains", "matches", "starts", "ends", "with", "upper", "lower", "case", "abs", "floor", "ceiling", "round"]);

/** The fields a condition reads: names of the record's own fields (previous.x counts as x). */
export function fieldsRead(feel: string | undefined, fields: Set<string>): string[] {
  const text = String(feel ?? "").replace(/"(?:[^"\\]|\\.)*"/g, '""');
  const out: string[] = [];
  for (const m of text.matchAll(/(?<![\w.])(previous\.)?([A-Za-z_]\w*)/g)) {
    const name = m[2];
    if (FEEL_WORDS.has(name) && !fields.has(name)) continue;
    if (fields.has(name) && !out.includes(name)) out.push(name);
  }
  return out;
}

const HINT_WORDS: Record<string, string> = {
  set_required: "makes required", set_visibility: "shows / hides", set_readonly: "locks",
  set_options: "limits the choices of", recommendation: "suggests a value for",
};

/** One record's rules as a diagram, laid out left to right. */
export function buildRuleGraph(views: StudioView[], catalogue: StudioCatalogue | null, entityName: string | null): RuleGraph {
  const ent = catalogue?.entities.find((e) => e.name === entityName) ?? null;
  const fields = new Set((ent?.fields ?? []).map((f) => f.name));
  const typeOf = (name: string) => ent?.fields.find((f) => f.name === name);
  const nodes = new Map<string, Omit<MapNode, "x" | "y">>();
  const edges: MapEdge[] = [];
  const add = (n: Omit<MapNode, "x" | "y" | "width" | "height">) => {
    if (!nodes.has(n.id)) {
      const [w, h] = SIZE[n.kind];
      nodes.set(n.id, { ...n, width: w, height: h });
    }
    return n.id;
  };
  const fieldDetail = (name: string) => {
    const f = typeOf(name);
    if (!f) return undefined;
    return f.type === "enum" ? `one of ${f.enumValues.slice(0, 3).join(", ")}${f.enumValues.length > 3 ? "…" : ""}` : f.type;
  };
  const read = (name: string) => add({ id: `read:${name}`, kind: "read", label: humanField(name), field: name, detail: fieldDetail(name) });
  const write = (name: string) => add({ id: `write:${name}`, kind: "write", label: humanField(name), field: name, detail: fieldDetail(name) });
  const flowName = (id?: string) => catalogue?.workflows.find((w) => w.id === id)?.name ?? id ?? "a workflow";

  for (const v of views) {
    if (v.entityName !== entityName || (v.kind !== "condition_action" && v.kind !== "decision_table")) continue;
    const r = v.rule;
    const rid = String(r.id);
    const ruleNode = add({ id: `rule:${rid}`, kind: "rule", label: r.name || rid, ruleId: rid, ruleKind: v.kind,
                           enabled: v.enabled, detail: rid });
    const reads = v.kind === "decision_table"
      ? (r.table?.inputs ?? []).map((c) => c.variableBinding || c.name).filter((n) => fields.has(n))
      : fieldsRead(r.when ?? r.expression, fields);
    for (const name of reads) edges.push({ id: `e:${read(name)}>${ruleNode}`, source: `read:${name}`, target: ruleNode, branch: "always", ruleId: rid });

    if (v.kind === "decision_table") {
      for (const c of r.table?.outputs ?? []) {
        const name = c.variableBinding || c.name;
        if (!fields.has(name)) continue;
        edges.push({ id: `e:${ruleNode}>${write(name)}`, source: ruleNode, target: `write:${name}`, branch: "table", ruleId: rid, label: "fills in" });
      }
    } else {
      for (const branch of ["then", "otherwise"] as const) {
        for (const [i, a] of (r[branch] ?? []).entries()) {
          const t = String(a.type);
          const label = branch === "otherwise" ? "otherwise" : undefined;
          if (t === "show_error") {
            const id = add({ id: `refuse:${rid}:${branch}`, kind: "refuse", label: "Stops the save", detail: a.message ?? "", ruleId: rid });
            edges.push({ id: `e:${ruleNode}>${id}`, source: ruleNode, target: id, branch, ruleId: rid, label });
          } else if ((t === "set_field" || t === "set_default" || t === "clear_field") && a.field) {
            const verb = t === "set_default" ? "fills in if empty" : t === "clear_field" ? "empties" : "fills in";
            edges.push({ id: `e:${ruleNode}>${write(a.field)}:${branch}:${i}`, source: ruleNode, target: `write:${a.field}`, branch, ruleId: rid,
                         label: branch === "otherwise" ? `otherwise ${verb}` : verb });
          } else if (HINT_WORDS[t] && a.field) {
            const id = add({ id: `hint:${a.field}`, kind: "hint", label: humanField(a.field), field: a.field, detail: "on the form" });
            const word = t === "set_required" && a.required === false ? "makes optional"
              : t === "set_visibility" && a.visible === false ? "hides" : t === "set_visibility" ? "shows"
              : t === "set_readonly" && a.readonly === false ? "unlocks" : HINT_WORDS[t];
            edges.push({ id: `e:${ruleNode}>${id}:${branch}:${i}`, source: ruleNode, target: id, branch, ruleId: rid,
                         label: `${branch === "otherwise" ? "otherwise " : ""}${word}` });
          } else if (t === "trigger_workflow" && a.workflow) {
            const id = add({ id: `wf:${a.workflow}`, kind: "workflow", label: flowName(a.workflow), detail: "starts it" });
            edges.push({ id: `e:${ruleNode}>${id}:${branch}:${i}`, source: ruleNode, target: id, branch, ruleId: rid, label: "starts" });
          } else if (t === "send_notification") {
            const id = add({ id: `notify:${rid}:${branch}:${i}`, kind: "notify", label: "Tells someone", detail: a.message ?? "", ruleId: rid });
            edges.push({ id: `e:${ruleNode}>${id}`, source: ruleNode, target: id, branch, ruleId: rid, label });
          }
        }
      }
    }
    // THE WORKFLOWS THAT USE IT: every one that saves this record checks it
    // (the ones that change what it looks at; if none do, every one that saves).
    if (v.enabled) {
      const links = v.usages?.links ?? [];
      const shown = links.some((l) => l.touches) ? links.filter((l) => l.touches) : links;
      for (const l of shown) {
        const id = add({ id: `wf:${l.workflow}`, kind: "workflow", label: l.name, detail: "checks it when saving" });
        edges.push({ id: `e:${ruleNode}>${id}:link:${l.step}`, source: ruleNode, target: id, branch: "always", ruleId: rid, label: "used in" });
      }
    }
    // An extra check someone added earlier in a workflow.
    for (const s of v.usages?.steps ?? []) {
      const id = add({ id: `wf:${s.workflow}`, kind: "workflow", label: s.name, detail: "checks it when saving" });
      edges.push({ id: `e:${ruleNode}>${id}:step`, source: ruleNode, target: id, branch: "always", ruleId: rid, label: "extra check in" });
    }
  }

  // Two ways out of one rule to the same place are drawn over each other: one
  // label says both ("requires · otherwise stops requiring"), the other none.
  const seen = new Map<string, MapEdge>();
  for (const e of edges) {
    const k = `${e.source}>${e.target}`;
    const first = seen.get(k);
    if (!first) { seen.set(k, e); continue; }
    if (e.label) first.label = [first.label, e.label].filter(Boolean).join(" · ");
    e.label = undefined;
  }

  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "LR", nodesep: 22, ranksep: 120, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const [id, n] of nodes) g.setNode(id, { width: n.width, height: n.height });
  for (const e of edges) g.setEdge(e.source, e.target, {}, e.id);
  dagre.layout(g);
  return {
    nodes: [...nodes.values()].map((n) => {
      const p = g.node(n.id);
      return { ...n, x: Math.round(p.x - n.width / 2), y: Math.round(p.y - n.height / 2) };
    }),
    edges,
  };
}

/** Everything one node touches, for hover: the node, its edges, and their ends. */
export function neighbourhood(graph: RuleGraph, nodeId: string): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set([nodeId]);
  const edges = new Set<string>();
  // A rule shows its whole chain; a field or an effect shows the rules on it and their chains.
  const rules = new Set<string>();
  if (nodeId.startsWith("rule:")) rules.add(nodeId);
  for (const e of graph.edges) {
    if (e.source === nodeId) rules.add(nodeId.startsWith("rule:") ? nodeId : e.target);
    if (e.target === nodeId && e.source.startsWith("rule:")) rules.add(e.source);
    if (e.source === nodeId && e.target.startsWith("rule:")) rules.add(e.target);
  }
  for (const e of graph.edges) {
    if (rules.has(e.source) || rules.has(e.target)) {
      edges.add(e.id);
      nodes.add(e.source);
      nodes.add(e.target);
    }
  }
  return { nodes, edges };
}

export type RuleState = "idle" | "held" | "missed" | "quiet" | "broken";
export interface RunLight {
  /** Per rule: held (acted on its then / a row matched), missed (acted on otherwise / no row), quiet (did not fire), broken. */
  rules: Map<string, RuleState>;
  /** Edges that carried this save: their order in the run, for the staggered light. */
  edges: Map<string, number>;
  /** Values on the fields: what was saved, and what the rules wrote. */
  values: Map<string, unknown>;
  written: Map<string, unknown>;
  refused: boolean;
}

/** A test run's trace, mapped onto the diagram. */
export function lightUp(graph: RuleGraph, views: StudioView[], answer: TestAnswer): RunLight {
  const rules = new Map<string, RuleState>();
  const order = new Map<string, number>();
  (answer.trace ?? []).forEach((t, i) => {
    order.set(String(t.id), i);
    const v = views.find((x) => String(x.rule.id) === String(t.id));
    let state: RuleState = "quiet";
    if (t.error) state = "broken";
    else if (t.fires && v?.kind === "decision_table") state = (t.matched?.length ?? 0) > 0 ? "held" : "missed";
    else if (t.fires) state = t.held ? "held" : "missed";
    rules.set(String(t.id), state);
  });
  const edges = new Map<string, number>();
  for (const e of graph.edges) {
    const state = rules.get(e.ruleId);
    const step = order.get(e.ruleId) ?? 0;
    if (!state || state === "quiet" || state === "broken") continue;
    const carried = e.branch === "always" && e.target.startsWith("rule:")   // a read
      || e.branch === "table" && state === "held"
      || e.branch === "then" && state === "held"
      || e.branch === "otherwise" && state === "missed";
    if (carried) edges.set(e.id, step);
  }
  const values = new Map(Object.entries(answer.record ?? {}));
  const written = new Map(Object.entries(answer.patches ?? {}));
  return { rules, edges, values, written, refused: !!answer.refused };
}
