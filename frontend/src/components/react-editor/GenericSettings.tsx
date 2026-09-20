"use client";
/**
 * What every element shows in Settings, whatever it is (PROP-001): each of
 * its values, editable; how it looks, in plain families (space, size,
 * colour); and when it is shown. A kind the registry names gets its own
 * words on top; anything else still gets all of this.
 */
import { useEffect, useState } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { DataPicker, type DataChoice } from "./DataPicker";
import { GROUP_BY_KEY, effectiveValue, getGroupValue, setGroupValue } from "./lib/classes";
import { bindingExpr, fieldChoices, pageSources, readBinding, rowContext, sampleOf, type DataSource } from "./lib/data";
import { humanise } from "./lib/templates";
import { useEditorStore } from "./store";
import type { ModelNode, Op, PageDoc, PropValue, SettingSpec } from "./types";

const NONE = "__none__";
//: Attributes that are the editor's or React's business, not the person's.
const HIDDEN = /^(className|key|ref|style|data-|aria-|children|dangerouslySetInnerHTML|suppressHydrationWarning|asChild|htmlFor|id|role|tabIndex)$|^(data-|aria-)/;
//: Handlers are behaviour, shown under "What happens when…".
const HANDLER = /^on[A-Z]/;

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <Label className="mb-1 block text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
      {help && <p className="mt-1 text-[10px] text-muted-foreground">{help}</p>}
    </div>
  );
}

function Debounced({ value, onCommit, ariaLabel, placeholder }: { value: string; onCommit: (v: string) => void; ariaLabel: string; placeholder?: string }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => { if (draft !== value) onCommit(draft); };
  return <Input className="h-8 text-xs" value={draft} placeholder={placeholder} aria-label={ariaLabel} onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />;
}

export function classesOf(node: ModelNode): string {
  const p = node.props.find((x) => x.name === "className");
  if (!p) return "";
  if (p.kind === "string") return p.value ?? "";
  const m = /^(?:cn|clsx|twMerge)\(\s*["'`]([^"'`]*)["'`]/.exec(p.value ?? "");
  return m ? m[1] : "";
}

export function classesDynamic(node: ModelNode): boolean {
  const p = node.props.find((x) => x.name === "className");
  return !!p && p.kind === "expr" && !/^(?:cn|clsx|twMerge)\(\s*["'`]/.test(p.value ?? "");
}

/** Plain names for attributes the registry does not describe. */
const PROP_LABELS: Record<string, string> = {
  placeholder: "Hint shown when empty", alt: "Description for screen readers", src: "Picture address", href: "Opens",
  title: "Tooltip", disabled: "Greyed out", required: "Must be filled in", readOnly: "Cannot be changed", checked: "Ticked",
  defaultValue: "Starts as", value: "Value", name: "Name used when sending", type: "Kind", variant: "Colour", size: "Size",
  label: "Label", description: "Description", target: "Opens in", rel: "Link relation", htmlFor: "For the field", id: "Identifier",
  colSpan: "Columns spanned", rowSpan: "Rows spanned", asChild: "Wraps its child", open: "Open", defaultOpen: "Starts open",
  orientation: "Direction", align: "Alignment", side: "Side", max: "Highest", min: "Lowest", step: "Step", rows: "Lines", cols: "Columns",
  autoFocus: "Focused at first", loading: "Loading", height: "Height", width: "Width", format: "Format", unit: "Unit", confirm: "Ask before doing it",
  successMessage: "Message when done", submitLabel: "Button text", columns: "Columns", redirectTo: "Then opens",
};

/** Every attribute the person may want to see: the ones no registry setting already names. */
export function ValuesSection({ nodes, doc, covered }: { nodes: ModelNode[]; doc: PageDoc; covered: Set<string> }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const node = nodes[0];
  const props = node.props.filter((p) => p.kind !== "spread" && !HIDDEN.test(p.name) && !HANDLER.test(p.name) && !covered.has(p.name)
    && !(node.type === "WidgetView" && ["widget", "data"].includes(p.name)) && !(["WorkflowForm", "WorkflowButton"].includes(node.type) && ["workflow", "fields", "input"].includes(p.name)));
  if (!props.length) return null;
  const commit = (name: string, value: PropValue | null) =>
    applyOps(nodes.map((n) => ({ op: "setProp", id: n.id, name, value }) as Op), `Change ${PROP_LABELS[name] ?? humanise(name)}`.toLowerCase().replace(/^change/, "Change"));
  return (
    <>
      {props.map((p) => {
        const label = PROP_LABELS[p.name] ?? humanise(p.name);
        const mixed = nodes.some((n) => (n.props.find((x) => x.name === p.name)?.value ?? null) !== (p.value ?? null));
        if (p.kind === "true" || (p.kind === "expr" && (p.value === "true" || p.value === "false"))) {
          const on = p.kind === "true" || p.value === "true";
          return <Field key={p.name} label={label}><div className="flex items-center gap-2"><Switch checked={on} aria-label={label} onCheckedChange={(v) => void commit(p.name, v ? { kind: "true" } : null)} /><span className="text-xs text-muted-foreground">{mixed ? "Mixed" : on ? "Yes" : "No"}</span></div></Field>;
        }
        if (p.kind === "expr" && /^-?\d+(\.\d+)?$/.test(p.value ?? "")) {
          return <Field key={p.name} label={label}><Input className="h-8 w-28 text-xs" type="number" defaultValue={p.value ?? ""} aria-label={label} onBlur={(e) => { if (e.target.value !== p.value) void commit(p.name, e.target.value === "" ? null : { kind: "expr", value: String(Number(e.target.value)) }); }} /></Field>;
        }
        if (p.kind === "expr") {
          const b = readBinding(doc, { ...node, exprOnly: p.value });
          return (
            <Field key={p.name} label={label} help={b.kind === "field" ? undefined : "Comes from something written for this page."}>
              {b.kind === "field" ? (
                <DataPicker doc={doc} nodeId={node.id} compact value={{ source: b.source, field: b.field }} onChange={(c) => c && void commit(p.name, { kind: "expr", value: bindingExpr(c.source, c.field) })} />
              ) : <Input className="h-8 font-mono text-[11px]" readOnly value={p.value ?? ""} aria-label={label} />}
            </Field>
          );
        }
        if (p.kind === "jsx") return <Field key={p.name} label={label} help="A piece of the page — select it on the canvas to change it."><Input className="h-8 font-mono text-[11px]" readOnly value={(p.value ?? "").slice(0, 60)} aria-label={label} /></Field>;
        return (
          <Field key={p.name} label={label}>
            <div className="flex gap-1">
              <Debounced value={p.value ?? ""} placeholder={mixed ? "Mixed" : undefined} ariaLabel={label} onCommit={(v) => void commit(p.name, v ? { kind: "string", value: v } : null)} />
              <Button size="sm" variant="ghost" className="h-8 px-2" title="Remove this value" onClick={() => void commit(p.name, null)}><X className="h-3 w-3" /></Button>
            </div>
          </Field>
        );
      })}
    </>
  );
}

/** How it looks — only the families that make sense for this element. */
export function LookSection({ nodes, doc }: { nodes: ModelNode[]; doc: PageDoc }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const node = nodes[0];
  const dynamic = classesDynamic(node);
  const classes = classesOf(node);
  const model = doc.model!;
  const isText = !node.children.length && (node.textEditable || !!node.exprOnly) && node.kind === "element";
  const holds = node.children.length > 0 || (node.kind === "element" && !node.selfClosing && !isText);
  const isFlex = getGroupValue(classes, "display", "") === "flex" || /\bflex\b/.test(classes);
  const isGrid = getGroupValue(classes, "display", "") === "grid";
  const groups: string[] = [];
  if (isText) groups.push("textSize", "fontWeight", "textColor", "textAlign");
  if (holds) groups.push("padding", isGrid ? "gridCols" : "gap");
  if (isFlex) groups.push("flexDirection", "justify", "items");
  const parentClasses = node.parent ? classesOf(model.nodes[node.parent]) : "";
  const inGrid = /^grid-cols-\d+$/.test(getGroupValue(parentClasses, "gridCols", "") ?? "");
  groups.push("marginTop", "marginBottom", "background", "rounded", inGrid ? "colSpan" : "width");
  if (node.type === "img" || node.type === "Image" || node.type === "Skeleton" || /^(div|section)$/.test(node.type) && !node.children.length) groups.push("height");
  const set = (group: string, slot: "" | "hover", v: string | null, label: string) =>
    applyOps(nodes.filter((n) => !classesDynamic(n)).map((n) => ({ op: "setClasses", id: n.id, classes: setGroupValue(classesOf(n), group, slot, v) }) as Op), label);
  if (dynamic) return <p className="mb-2 text-[11px] text-muted-foreground">This item's look is decided by code as the app runs — ask Smith to change it.</p>;
  return (
    <>
      {groups.map((key) => {
        const g = GROUP_BY_KEY[key];
        const eff = effectiveValue(classes, key, "");
        return (
          <Field key={key} label={g.label}>
            <Select value={eff.value ?? NONE} onValueChange={(v) => void set(key, "", v === NONE ? null : v, `Change ${g.label.toLowerCase()}`)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Default" /></SelectTrigger>
              <SelectContent><SelectItem value={NONE}>Default</SelectItem>{(g.options ?? []).map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
        );
      })}
      {(isText || holds || node.type === "Button") && (
        <div className="mb-3 rounded-md border border-dashed border-border p-2">
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">When the mouse is over it</p>
          {(["background", "textColor"] as const).filter((k) => k !== "textColor" || isText || node.type === "Button").map((key) => {
            const g = GROUP_BY_KEY[key];
            const v = getGroupValue(classes, key, "hover");
            return (
              <Field key={key} label={g.label}>
                <Select value={v ?? NONE} onValueChange={(nv) => void set(key, "hover", nv === NONE ? null : nv, `Change ${g.label.toLowerCase()} on hover`)}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="No change" /></SelectTrigger>
                  <SelectContent><SelectItem value={NONE}>No change</SelectItem>{(g.options ?? []).map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
            );
          })}
        </div>
      )}
      <span className="hidden">{model.roots.length}</span>
    </>
  );
}

// ---------------------------------------------------------------------------
// "Show this when…" (UX-003) — a condition chosen, never typed
// ---------------------------------------------------------------------------

export interface Condition { source: DataSource; field: string; op: "is" | "is-not" | "has" | "empty"; value: string }

export function parseCondition(doc: PageDoc, node: ModelNode): Condition | null {
  const cond = node.condition?.trim();
  if (!cond) return null;
  const m = /^([\w$.?]+?)(?:\?\.|\.)?([\w$]+)?\s*(===|!==)\s*("([^"]*)"|(\d+(?:\.\d+)?)|true|false)$/.exec(cond)
    ?? /^(!?)([\w$.?]+)$/.exec(cond);
  if (!m) return null;
  const sources = [...(rowContext(doc, node.id) ? [rowContext(doc, node.id)!] : []), ...pageSources(doc)];
  const find = (expr: string) => {
    const norm = expr.replace(/\?\./g, ".");
    for (const s of sources) {
      const base = s.expr.replace(/\?\./g, ".");
      if (norm === base) return { source: s, field: "" };
      if (norm.startsWith(base + ".")) return { source: s, field: norm.slice(base.length + 1) };
    }
    return null;
  };
  if (m.length === 3) {
    const hit = find(m[2]);
    return hit ? { ...hit, op: m[1] ? "empty" : "has", value: "" } : null;
  }
  const hit = find(m[2] ? `${m[1]}.${m[2]}` : m[1]);
  if (!hit) return null;
  const raw = m[4].startsWith('"') ? m[5] : m[4];
  return { ...hit, op: m[3] === "===" ? "is" : "is-not", value: raw };
}

export function conditionExpr(c: Condition): string {
  const opt = c.source.shape.kind === "record" ? "?." : ".";
  const base = c.field ? `${c.source.expr}${opt}${c.field}` : c.source.expr;
  if (c.op === "has") return base;
  if (c.op === "empty") return `!${base}`;
  const lit = /^-?\d+(\.\d+)?$/.test(c.value) || c.value === "true" || c.value === "false" ? c.value : JSON.stringify(c.value);
  return `${base} ${c.op === "is" ? "===" : "!=="} ${lit}`;
}

export function ShowWhenControl({ node, doc }: { node: ModelNode; doc: PageDoc }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const current = parseCondition(doc, node);
  const custom = !!node.condition && !current;
  const [mode, setMode] = useState<"always" | "when">(node.condition ? "when" : "always");
  const [draft, setDraft] = useState<Condition | null>(current);
  useEffect(() => { setMode(node.condition ? "when" : "always"); setDraft(current); }, [node.id, node.condition]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!node.parent) return null;
  const choice: DataChoice | null = draft ? { source: draft.source, field: draft.field } : null;
  const fieldInfo = draft ? fieldChoices(doc, draft.source).find((f) => f.name === draft.field) : null;
  const options = fieldInfo && draft ? (doc.entities.find((e) => e.name === draft.source.entity?.name)?.fields.find((f) => f.name === draft.field)?.options ?? []) : [];
  const samples = draft?.source.entity ? [...new Set((doc.samples?.[draft.source.entity.name] ?? []).map((r) => String(r[draft.field] ?? "")).filter(Boolean))].slice(0, 8) : [];
  const values = [...new Set([...options, ...samples])];
  const apply = (c: Condition) => applyOps([{ op: "wrapCondition", id: node.id, expr: conditionExpr(c) }], "Show only when…");
  return (
    <Field label="Show this" help={custom ? `Currently: when ${node.condition} — a condition written for this page. Choosing here replaces it.` : undefined}>
      <Select value={mode} onValueChange={(v) => {
        setMode(v as "always" | "when");
        if (v === "always" && node.condition) void applyOps([{ op: "unwrapCondition", id: node.id }], "Always show");
      }}>
        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="always">Always</SelectItem><SelectItem value="when">Only when…</SelectItem></SelectContent>
      </Select>
      {mode === "when" && (
        <div className="mt-1 space-y-1 rounded-md border border-border p-2">
          <DataPicker doc={doc} nodeId={node.id} compact value={choice} onChange={(c) => { if (!c) return; const next: Condition = { source: c.source, field: c.field, op: draft?.op ?? "is", value: "" }; setDraft(next); if (next.op === "has" || next.op === "empty") void apply(next); }} />
          {draft && (
            <div className="flex gap-1">
              <Select value={draft.op} onValueChange={(v) => { const next = { ...draft, op: v as Condition["op"] }; setDraft(next); if (v === "has" || v === "empty" || next.value) void apply(next); }}>
                <SelectTrigger className="h-8 w-32 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="is">is</SelectItem><SelectItem value="is-not">is not</SelectItem><SelectItem value="has">has a value</SelectItem><SelectItem value="empty">is empty</SelectItem></SelectContent>
              </Select>
              {(draft.op === "is" || draft.op === "is-not") && (values.length ? (
                <Select value={draft.value || NONE} onValueChange={(v) => { const next = { ...draft, value: v }; setDraft(next); void apply(next); }}>
                  <SelectTrigger className="h-8 flex-1 text-xs"><SelectValue placeholder="Choose a value" /></SelectTrigger>
                  <SelectContent>{values.map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}</SelectContent>
                </Select>
              ) : (
                <Input className="h-8 flex-1 text-xs" placeholder="a value" defaultValue={draft.value} aria-label="Value" onBlur={(e) => { const next = { ...draft, value: e.target.value }; setDraft(next); if (e.target.value) void apply(next); }} />
              ))}
            </div>
          )}
          {draft && draft.source && <p className="text-[10px] text-muted-foreground">Example now: {sampleOf(doc, draft.source, draft.field) || "—"}</p>}
        </div>
      )}
    </Field>
  );
}

/** Which registry settings already cover an attribute, so it is not shown twice. */
export function coveredProps(specs: SettingSpec[]): Set<string> {
  const out = new Set<string>();
  for (const s of specs) if (s.target.kind === "prop" || s.target.kind === "page" || s.target.kind === "workflow") out.add(s.target.name);
  return out;
}

export { cn };
