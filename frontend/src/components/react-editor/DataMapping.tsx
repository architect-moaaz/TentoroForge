"use client";
/**
 * Visual mapping (DATA-002/003): what a piece of text shows, what a form's
 * fields are and where a fixed value comes from, and what a button hands to
 * its workflow. Each control edits a structured binding; the expression is
 * written from it, and the compiler checks the result before it is saved.
 */
import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { DataPicker, type DataChoice } from "./DataPicker";
import { bindingExpr, entry, entryString, fieldChoices, readBinding, withExpr, withString } from "./lib/data";
import { humanise } from "./lib/templates";
import { useEditorStore } from "./store";
import type { ModelNode, ObjectEntry, PageDoc, WorkflowInput, WorkflowRef } from "./types";

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <Label className="mb-1 block text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
      {help && <p className="mt-1 text-[10px] text-muted-foreground">{help}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// "Shows" — fixed text or a value from the page's data
// ---------------------------------------------------------------------------

export function ShowsControl({ node, doc }: { node: ModelNode; doc: PageDoc }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const setText = useEditorStore((s) => s.setText);
  const current = readBinding(doc, node);
  const [mode, setMode] = useState<"text" | "data">(current.kind === "field" ? "data" : "text");
  const [draft, setDraft] = useState(node.text ?? "");
  useEffect(() => { setMode(current.kind === "field" ? "data" : "text"); setDraft(node.textEditable ? node.text ?? "" : ""); }, [node.id, current.kind, node.text, node.textEditable]);
  const choice: DataChoice | null = current.kind === "field" ? { source: current.source, field: current.field } : null;

  if (current.kind === "custom") {
    return (
      <Field label="Shows" help="This comes from something written for this page. Ask Smith to change it, or choose data below to replace it.">
        <Input className="h-8 font-mono text-[11px]" readOnly value={current.code} aria-label="Shows" />
        <div className="mt-1"><DataPicker doc={doc} nodeId={node.id} value={null} onChange={(c) => c && void bind(c)} compact /></div>
      </Field>
    );
  }

  async function bind(c: DataChoice) {
    const f = fieldChoices(doc, c.source).find((x) => x.name === c.field);
    const expr = bindingExpr(c.source, c.field, { text: true, type: f?.type });
    await applyOps([{ op: "setChildren", id: node.id, jsx: `{${expr}}` }], `Show ${f?.label ?? c.source.label}`);
  }

  return (
    <Field label="Shows">
      <div className="mb-1 flex rounded-md bg-muted p-0.5 text-xs" role="group" aria-label="Fixed text or data">
        <button type="button" className={cn("flex-1 rounded px-2 py-1", mode === "text" ? "bg-background font-medium shadow-sm" : "text-muted-foreground")} onClick={() => setMode("text")}>Fixed text</button>
        <button type="button" className={cn("flex-1 rounded px-2 py-1", mode === "data" ? "bg-background font-medium shadow-sm" : "text-muted-foreground")} onClick={() => setMode("data")}>From the page's data</button>
      </div>
      {mode === "text" ? (
        <Input className="h-8 text-xs" value={draft} aria-label="Text" placeholder={current.kind === "field" ? "Type text to replace the data" : ""}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            const was = node.textEditable ? node.text ?? "" : "";
            if (draft === was || (!draft && current.kind !== "field")) return;
            // Replacing data with words: the element's content becomes plain text again.
            if (current.kind === "field") void applyOps([{ op: "setChildren", id: node.id, jsx: /[{}<>&]/.test(draft) ? `{${JSON.stringify(draft)}}` : draft }], "Change text");
            else void setText(node.id, draft);
          }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      ) : (
        <DataPicker doc={doc} nodeId={node.id} value={choice} onChange={(c) => c && void bind(c)} />
      )}
    </Field>
  );
}

// ---------------------------------------------------------------------------
// A form's fields
// ---------------------------------------------------------------------------

const KINDS = [
  { value: "text", label: "Short text" }, { value: "textarea", label: "Longer text" }, { value: "email", label: "Email address" },
  { value: "number", label: "Number" }, { value: "date", label: "Date" }, { value: "datetime", label: "Date and time" },
  { value: "select", label: "One of a list" }, { value: "checkbox", label: "Yes or no" }, { value: "password", label: "Password" },
  { value: "url", label: "Web address" }, { value: "tel", label: "Phone number" },
];

function choiceFromCode(doc: PageDoc, nodeId: string, code: string | undefined): DataChoice | null {
  if (!code) return null;
  const fake: ModelNode = { ...doc.model!.nodes[nodeId], exprOnly: code };
  const b = readBinding(doc, fake);
  return b.kind === "field" ? { source: b.source, field: b.field } : null;
}

export function FormFieldsEditor({ node, doc, workflow }: { node: ModelNode; doc: PageDoc; workflow: WorkflowRef | null }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const busy = useEditorStore((s) => s.busy);
  const entries = node.objects?.fields ?? [];
  const inputs: WorkflowInput[] = workflow?.inputs ?? [];
  const names = [...new Set([...inputs.map((i) => i.name), ...entries.map((e) => e.key)])];
  const [open, setOpen] = useState<string | null>(null);

  const save = (next: ObjectEntry[], label: string) => applyOps([{ op: "setObjectProp", id: node.id, name: "fields", entries: next }], label);
  const setField = (name: string, fn: (e: ObjectEntry[]) => ObjectEntry[], label: string) => {
    const cur = entry(entries, name);
    const inner = cur && cur.kind === "object" ? cur.entries ?? [] : [];
    const nextInner = fn(inner);
    const next = [...entries.filter((e) => e.key !== name), { key: name, kind: "object" as const, code: "", entries: nextInner }];
    // Keep the workflow's order.
    next.sort((a, b) => names.indexOf(a.key) - names.indexOf(b.key));
    return save(next, label);
  };

  if (!names.length) return <p className="text-[11px] text-muted-foreground">This form has no fields — choose a workflow for it first.</p>;
  return (
    <div className="space-y-1">
      {names.map((name) => {
        const e = entry(entries, name);
        const inner = e && e.kind === "object" ? e.entries ?? [] : null;
        const input = inputs.find((i) => i.name === name);
        const custom = e && e.kind !== "object";
        const fixed = inner ? entry(inner, "value") : undefined;
        const label = inner ? entryString(inner, "label") || humanise(name) : humanise(name);
        const isOpen = open === name;
        return (
          <div key={name} className="rounded-md border border-border">
            <button type="button" className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs" onClick={() => setOpen(isOpen ? null : name)} aria-expanded={isOpen}>
              <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
              <span className="text-[10px] text-muted-foreground">{custom ? "custom" : fixed ? "from the page" : !e ? "not shown" : (KINDS.find((k) => k.value === (entryString(inner!, "kind") || "text"))?.label ?? "Short text")}{input?.required ? " · required" : ""}</span>
            </button>
            {isOpen && (
              <div className="border-t border-border px-2 pt-2">
                {custom ? (
                  <p className="mb-2 text-[11px] text-muted-foreground">This field is set up in a way written for this page — ask Smith to change it.</p>
                ) : (
                  <>
                    <Field label="Filled in by">
                      <Select value={fixed ? "page" : e ? "person" : "hidden"} disabled={busy} onValueChange={(v) => {
                        if (v === "person") void setField(name, (cur) => cur.filter((x) => x.key !== "value").concat(entryString(cur, "label") ? [] : [{ key: "label", kind: "string", value: humanise(name), code: JSON.stringify(humanise(name)) }]), `Field ${label} typed by the person`);
                        else if (v === "page") void setField(name, () => [], `Field ${label} from the page`);
                        else void save(entries.filter((x) => x.key !== name), `Hide field ${label}`);
                      }}>
                        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="person">The person, in the form</SelectItem>
                          <SelectItem value="page">The page — a value it already has</SelectItem>
                          {!input?.required && <SelectItem value="hidden">Nobody — leave it out</SelectItem>}
                        </SelectContent>
                      </Select>
                    </Field>
                    {e && fixed !== undefined && (
                      <Field label="Which value" help={input?.kind === "record" ? `“${humanise(name)}” is a record — choose the one this page is about.` : undefined}>
                        <DataPicker doc={doc} nodeId={node.id} want={input?.kind === "record" ? "id" : undefined} compact
                          value={choiceFromCode(doc, node.id, fixed.code)}
                          onChange={(c) => { if (c) void setField(name, (cur) => withExpr(cur, "value", input?.kind === "record" ? `${c.source.expr}${c.source.shape.kind === "record" ? "?." : "."}id` : bindingExpr(c.source, c.field)), `Field ${label} from ${c.source.label}`); }} />
                        {!fixed.code.match(/^[\w$.?]+$/) && <p className="mt-1 text-[10px] text-muted-foreground">Currently: <code>{fixed.code}</code></p>}
                      </Field>
                    )}
                    {e && fixed === undefined && (
                      <>
                        <Field label="Label"><Input className="h-8 text-xs" defaultValue={entryString(inner!, "label")} disabled={busy} aria-label="Label" onBlur={(ev) => { if (ev.target.value !== entryString(inner!, "label")) void setField(name, (cur) => withString(cur, "label", ev.target.value), `Relabel ${label}`); }} /></Field>
                        <Field label="Kind of information">
                          <Select value={entryString(inner!, "kind") || (input?.options?.length ? "select" : "text")} disabled={busy} onValueChange={(v) => void setField(name, (cur) => withString(cur, "kind", v === "text" ? "" : v), `Field ${label} is ${v}`)}>
                            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                            <SelectContent>{KINDS.map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}</SelectContent>
                          </Select>
                        </Field>
                        {(entryString(inner!, "kind") === "select" || (!entryString(inner!, "kind") && input?.options?.length)) && (
                          <Field label="Choices" help="One per line.">
                            <textarea className="min-h-[3.5rem] w-full rounded-md border border-input bg-background px-2 py-1 text-xs" disabled={busy} aria-label="Choices"
                              defaultValue={(entry(inner!, "options")?.items ?? []).map((it) => entryString(it, "label") || entryString(it, "value")).join("\n") || (input?.options ?? []).join("\n")}
                              onBlur={(ev) => { const opts = ev.target.value.split("\n").map((x) => x.trim()).filter(Boolean); void setField(name, (cur) => [...cur.filter((x) => x.key !== "options"), { key: "options", kind: "objects", code: "", items: opts.map((o) => [{ key: "label", kind: "string", value: o, code: JSON.stringify(o) }, { key: "value", kind: "string", value: o, code: JSON.stringify(o) }]) }], `Choices of ${label}`); }} />
                          </Field>
                        )}
                        <Field label="Hint shown when empty"><Input className="h-8 text-xs" defaultValue={entryString(inner!, "placeholder")} disabled={busy} aria-label="Hint" onBlur={(ev) => { if (ev.target.value !== entryString(inner!, "placeholder")) void setField(name, (cur) => withString(cur, "placeholder", ev.target.value), `Hint of ${label}`); }} /></Field>
                        <Field label="Help text under it"><Input className="h-8 text-xs" defaultValue={entryString(inner!, "help")} disabled={busy} aria-label="Help text" onBlur={(ev) => { if (ev.target.value !== entryString(inner!, "help")) void setField(name, (cur) => withString(cur, "help", ev.target.value), `Help of ${label}`); }} /></Field>
                      </>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}
      <p className="text-[10px] text-muted-foreground">Required information must be filled in by the person or come from the page; the app refuses a form that leaves it out.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// What a button hands to its workflow
// ---------------------------------------------------------------------------

export function WorkflowInputEditor({ node, doc, workflow }: { node: ModelNode; doc: PageDoc; workflow: WorkflowRef | null }) {
  const applyOps = useEditorStore((s) => s.applyOps);
  const busy = useEditorStore((s) => s.busy);
  const entries = node.objects?.input ?? [];
  const inputs = workflow?.inputs ?? [];
  const [fixedDraft, setFixedDraft] = useState<Record<string, string>>({});
  if (!workflow) return <p className="text-[11px] text-muted-foreground">Choose a workflow for this button first.</p>;
  if (!inputs.length) return <p className="text-[11px] text-muted-foreground">“{workflow.name}” needs nothing from this page.</p>;
  const save = (next: ObjectEntry[], label: string) => applyOps([{ op: "setObjectProp", id: node.id, name: "input", entries: next }], label);
  return (
    <div className="space-y-2">
      {inputs.map((input) => {
        const e = entry(entries, input.name);
        const choice = choiceFromCode(doc, node.id, e?.kind === "expr" ? e.code : undefined);
        const isFixed = e && (e.kind === "string" || e.kind === "number" || e.kind === "boolean");
        const missing = !e && input.required;
        return (
          <div key={input.name} className={cn("rounded-md border p-2", missing ? "border-amber-300 bg-amber-50/50 dark:bg-amber-950/20" : "border-border")}>
            <div className="mb-1 flex items-center gap-1 text-xs">
              <span className="font-medium">{humanise(input.name)}</span>
              {input.required && <span className="text-[10px] text-muted-foreground">required</span>}
              {missing && <span className="ml-auto text-[10px] text-amber-700">not given yet</span>}
            </div>
            <Select value={isFixed ? "fixed" : e ? "page" : "none"} disabled={busy} onValueChange={(v) => {
              if (v === "none") void save(entries.filter((x) => x.key !== input.name), `Clear ${humanise(input.name)}`);
              else if (v === "fixed") void save([...entries.filter((x) => x.key !== input.name), { key: input.name, kind: "string", value: fixedDraft[input.name] ?? "", code: JSON.stringify(fixedDraft[input.name] ?? "") }], `Fix ${humanise(input.name)}`);
              else void save(withExpr(entries, input.name, "undefined as never"), `${humanise(input.name)} from the page`);
            }}>
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Where from?" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="page">From the page's data</SelectItem>
                <SelectItem value="fixed">Always the same value</SelectItem>
                {!input.required && <SelectItem value="none">Nothing</SelectItem>}
              </SelectContent>
            </Select>
            {e && !isFixed && (
              <div className="mt-1">
                <DataPicker doc={doc} nodeId={node.id} want={input.kind === "record" ? "id" : undefined} compact value={choice}
                  onChange={(c) => { if (c) void save(withExpr(entries, input.name, input.kind === "record" ? `${c.source.expr}${c.source.shape.kind === "record" ? "?." : "."}id` : bindingExpr(c.source, c.field)), `${humanise(input.name)} from ${c.source.label}`); }} />
              </div>
            )}
            {isFixed && (
              input.options?.length ? (
                <Select value={String(e.value ?? "")} disabled={busy} onValueChange={(v) => void save([...entries.filter((x) => x.key !== input.name), { key: input.name, kind: "string", value: v, code: JSON.stringify(v) }], `${humanise(input.name)} is ${v}`)}>
                  <SelectTrigger className="mt-1 h-8 text-xs"><SelectValue placeholder="Choose" /></SelectTrigger>
                  <SelectContent>{input.options.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
                </Select>
              ) : (
                <Input className="mt-1 h-8 text-xs" defaultValue={String(e.value ?? "")} disabled={busy} aria-label={`Value of ${humanise(input.name)}`}
                  onChange={(ev) => setFixedDraft({ ...fixedDraft, [input.name]: ev.target.value })}
                  onBlur={(ev) => { const v = ev.target.value; const isNum = /number|int|decimal/.test(input.type); if (v !== String(e.value ?? "")) void save([...entries.filter((x) => x.key !== input.name), isNum && v !== "" && !isNaN(Number(v)) ? { key: input.name, kind: "number", value: Number(v), code: String(Number(v)) } : { key: input.name, kind: "string", value: v, code: JSON.stringify(v) }], `${humanise(input.name)} is ${v}`); }} />
              )
            )}
          </div>
        );
      })}
      {entries.some((e) => !inputs.find((i) => i.name === e.key)) && (
        <p className="text-[10px] text-muted-foreground">Also sends: {entries.filter((e) => !inputs.find((i) => i.name === e.key)).map((e) => e.key).join(", ")}.</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// A chart's filters — "only records where …"
// ---------------------------------------------------------------------------

export function FilterEditor({ entity, samples, value, onChange, disabled }: {
  entity: { name: string; fields: { name: string; label: string; type: string; options: string[] }[] } | null;
  samples: Record<string, unknown>[];
  value: Record<string, string | string[] | number | boolean>;
  onChange: (next: Record<string, string | string[] | number | boolean>) => void;
  disabled?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  if (!entity) return null;
  const fields = entity.fields.filter((f) => !/^id$/.test(f.name) && !/date|time/.test(f.type));
  const valuesOf = (name: string): string[] => {
    const f = entity.fields.find((x) => x.name === name);
    if (f?.options?.length) return f.options;
    return [...new Set(samples.map((r) => String(r[name] ?? "")).filter(Boolean))].slice(0, 12);
  };
  const rows = Object.entries(value);
  return (
    <div className="space-y-1">
      {rows.map(([k, v]) => {
        const chosen = Array.isArray(v) ? v.map(String) : [String(v)];
        const options = [...new Set([...valuesOf(k), ...chosen])];
        return (
          <div key={k} className="rounded-md border border-border p-2 text-xs">
            <div className="mb-1 flex items-center gap-1">
              <span className="font-medium">{entity.fields.find((f) => f.name === k)?.label ?? humanise(k)}</span><span className="text-muted-foreground">is any of</span>
              <button type="button" className="ml-auto rounded p-0.5 text-muted-foreground hover:bg-muted" aria-label="Remove this condition" disabled={disabled}
                onClick={() => { const next = { ...value }; delete next[k]; onChange(next); }}><X className="h-3 w-3" /></button>
            </div>
            <div className="flex flex-wrap gap-1">
              {options.map((o) => (
                <button key={o} type="button" disabled={disabled} aria-pressed={chosen.includes(o)}
                  className={cn("rounded-full border px-2 py-0.5 text-[11px]", chosen.includes(o) ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted")}
                  onClick={() => { const next = chosen.includes(o) ? chosen.filter((x) => x !== o) : [...chosen, o]; onChange({ ...value, [k]: next }); }}>{o}</button>
              ))}
            </div>
          </div>
        );
      })}
      {adding ? (
        <Select onValueChange={(f) => { setAdding(false); onChange({ ...value, [f]: [] }); }}>
          <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Only where…" /></SelectTrigger>
          <SelectContent>{fields.filter((f) => !(f.name in value)).map((f) => <SelectItem key={f.name} value={f.name}>{f.label || humanise(f.name)}</SelectItem>)}</SelectContent>
        </Select>
      ) : (
        <Button size="sm" variant="outline" className="h-7 text-xs" disabled={disabled || fields.every((f) => f.name in value)} onClick={() => setAdding(true)}><Plus className="h-3 w-3" /> Only include…</Button>
      )}
    </div>
  );
}

/** A picture of a query over the sample rows, before the chart exists. */
export function ChartPreview({ rows, mark, dimension, measureKey }: { rows: Record<string, string | number | null>[]; mark: string; dimension: string | null; measureKey: string }) {
  if (!rows.length) return <p className="py-4 text-center text-[11px] text-muted-foreground">Nothing matches — loosen the filters.</p>;
  const max = Math.max(...rows.map((r) => Number(r[measureKey]) || 0), 1);
  const total = rows.reduce((a, r) => a + (Number(r[measureKey]) || 0), 0) || 1;
  const palette = ["hsl(217 91% 60%)", "hsl(25 95% 53%)", "hsl(142 71% 45%)", "hsl(280 67% 60%)", "hsl(0 84% 60%)", "hsl(48 96% 53%)", "hsl(190 90% 45%)", "hsl(330 80% 60%)"];
  if (!dimension) {
    return <p className="py-2 text-center text-2xl font-semibold tabular-nums">{rows[0][measureKey]}</p>;
  }
  if (mark === "graph") {
    const keys = Object.keys(rows[0]).filter((k) => k !== measureKey);
    const [from, to] = keys;
    return (
      <ul className="space-y-0.5 text-[10px]">
        {rows.slice(0, 8).map((r, i) => (
          <li key={i} className="flex items-center gap-1">
            <span className="truncate text-muted-foreground">{String(r[from] ?? "")}</span>
            <span className="h-px flex-1 bg-border" style={{ height: `${Math.max(1, (4 * (Number(r[measureKey]) || 0)) / max)}px` }} />
            <span className="truncate text-muted-foreground">{to ? String(r[to] ?? "") : "?"}</span>
            <span className="ml-1 tabular-nums">{r[measureKey]}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (mark === "map") {
    return (
      <ul className="grid grid-cols-2 gap-x-2 text-[10px]">
        {rows.slice(0, 10).map((r, i) => (
          <li key={i} className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm" style={{ background: `hsl(217 91% 60% / ${0.25 + (0.75 * (Number(r[measureKey]) || 0)) / max})` }} />
            <span className="truncate text-muted-foreground">{String(r[dimension])}</span>
            <span className="ml-auto tabular-nums">{r[measureKey]}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (mark === "heatmap" || mark === "scatter") {
    const keys = Object.keys(rows[0]);
    return (
      <table className="w-full text-[10px]">
        <thead><tr>{keys.map((k) => <th key={k} className="pb-1 text-left font-medium text-muted-foreground">{k}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 6).map((r, i) => <tr key={i}>{keys.map((k) => <td key={k} className="py-0.5 pr-2 tabular-nums">{String(r[k] ?? "")}</td>)}</tr>)}</tbody>
      </table>
    );
  }
  if (mark === "pie" || mark === "donut" || mark === "funnel" || mark === "treemap" || mark === "sunburst") {
    return (
      <div>
        <div className="flex h-4 w-full overflow-hidden rounded-full">
          {rows.map((r, i) => <div key={i} style={{ width: `${(100 * (Number(r[measureKey]) || 0)) / total}%`, background: palette[i % palette.length] }} title={`${r[dimension]}: ${r[measureKey]}`} />)}
        </div>
        <ul className="mt-1 grid grid-cols-2 gap-x-2 text-[10px] text-muted-foreground">
          {rows.slice(0, 8).map((r, i) => <li key={i} className="flex items-center gap-1"><span className="h-2 w-2 rounded-full" style={{ background: palette[i % palette.length] }} />{String(r[dimension])} · {r[measureKey]}</li>)}
        </ul>
      </div>
    );
  }
  return (
    <ul className="space-y-1">
      {rows.slice(0, 8).map((r, i) => (
        <li key={i} className="flex items-center gap-2 text-[10px]">
          <span className="w-20 truncate text-muted-foreground" title={String(r[dimension])}>{String(r[dimension])}</span>
          <span className="h-3 rounded-sm" style={{ width: `${Math.max(2, (100 * (Number(r[measureKey]) || 0)) / max)}%`, background: mark === "line" || mark === "area" ? "hsl(217 91% 60% / 0.5)" : palette[0] }} />
          <span className="tabular-nums">{r[measureKey]}</span>
        </li>
      ))}
    </ul>
  );
}
