"use client";
/**
 * Add a chart or a number tile (UX-003): one decision at a time — which
 * records, what to count or add up, what to group by, how to draw it, what
 * to call it — with a live summary. What comes out is a Blueprint widget,
 * checked by the same rules the analytics agent obeys, read in `load.ts`
 * and drawn by `WidgetView` on the app's own ECharts chart.
 */
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { editorApi, failureOf } from "./api";
import { ChartPreview, FilterEditor } from "./DataMapping";
import { insertionTarget } from "./LeftPanel";
import { sampleQuery } from "./lib/data";
import { MARKS, humanise, measureLabel, widgetOps } from "./lib/templates";
import { useEditorStore } from "./store";
import type { ChartMark, ComponentDef, EntityRef, WidgetDimension, WidgetMeasure, WidgetSpec } from "./types";

const NUMERIC = /int|number|decimal|float|numeric|money|currency/;
const DATE = /date|time/;

export function numericFields(entity: EntityRef) {
  return entity.fields.filter((f) => NUMERIC.test(f.type.toLowerCase()) && !/^id$|Id$/.test(f.name));
}
export function groupableFields(entity: EntityRef) {
  return entity.fields.filter((f) => !/^id$/.test(f.name) && !NUMERIC.test(f.type.toLowerCase()) && !/text/.test(f.type.toLowerCase()))
    .map((f) => ({ ...f, isDate: DATE.test(f.type.toLowerCase()) }));
}

function Choice({ checked, onChange, children, name }: { checked: boolean; onChange: () => void; children: React.ReactNode; name: string }) {
  return (
    <label className={cn("flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm", checked ? "border-primary bg-primary/5" : "border-border")}>
      <input type="radio" name={name} className="mt-1" checked={checked} onChange={onChange} />
      <span className="min-w-0">{children}</span>
    </label>
  );
}

export function ChartDialog({ def, onClose }: { def: ComponentDef; onClose: () => void }) {
  const doc = useEditorStore((s) => s.doc)!;
  const projectId = useEditorStore((s) => s.projectId)!;
  const selection = useEditorStore((s) => s.selection);
  const applyOps = useEditorStore((s) => s.applyOps);
  const reload = useEditorStore((s) => s.reload);
  const kind: "chart" | "metric" = def.guide === "metric" ? "metric" : "chart";
  const [step, setStep] = useState(0);
  const [entityId, setEntityId] = useState(doc.entities[0]?.id ?? "");
  const [measure, setMeasure] = useState<WidgetMeasure>({ key: "count", aggregation: "count" });
  const [dimension, setDimension] = useState<WidgetDimension | null>(null);
  const [mark, setMark] = useState<ChartMark>("bar");
  const [stacked, setStacked] = useState(false);
  const [horizontal, setHorizontal] = useState(false);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<Record<string, string | string[] | number | boolean>>({});
  const [split, setSplit] = useState<string | null>(null);
  const [sort, setSort] = useState<"biggest" | "smallest" | "name" | "auto">("auto");
  const [limit, setLimit] = useState<number | null>(null);
  const entity = doc.entities.find((e) => e.id === entityId) ?? null;
  const nums = entity ? numericFields(entity) : [];
  const groups = entity ? groupableFields(entity) : [];

  const measures: WidgetMeasure[] = useMemo(() => {
    const out: WidgetMeasure[] = [{ key: "count", aggregation: "count" }];
    for (const f of nums) out.push({ key: `total_${f.name}`, aggregation: "sum", field: f.name }, { key: `average_${f.name}`, aggregation: "avg", field: f.name });
    return out;
  }, [nums]);

  const dimensions = [...(dimension ? [dimension] : []), ...(split && split !== dimension?.field ? [{ field: split }] : [])];
  const sortSpec = sort === "biggest" ? { by: measure.key, order: "desc" as const } : sort === "smallest" ? { by: measure.key, order: "asc" as const } : sort === "name" && dimension ? { by: dimension.field, order: "asc" as const } : null;
  const preview = entity ? sampleQuery(doc.samples?.[entity.name] ?? [], { measures: [measure], dimensions: kind === "metric" ? [] : dimensions, filter, sort: sortSpec, limit }) : [];

  const defaultTitle = entity
    ? (kind === "metric" ? measureLabel(measure, entity.name) : `${measureLabel(measure, entity.name)} by ${dimension ? humanise(dimension.field).toLowerCase() : "…"}`)
    : "";
  const title = label.trim() || defaultTitle;

  const steps: { title: string; body: React.ReactNode; ok: boolean }[] = [
    {
      title: "Which records is it about?", ok: !!entity,
      body: doc.entities.length ? <div className="space-y-1">{doc.entities.map((e) => (
        <Choice key={e.id} name="ent" checked={entityId === e.id} onChange={() => { setEntityId(e.id); setMeasure({ key: "count", aggregation: "count" }); setDimension(null); }}>
          <span className="font-medium">{e.name}</span><span className="block text-xs text-muted-foreground">{e.fields.length} fields</span>
        </Choice>))}</div>
        : <p className="text-sm text-muted-foreground">This application has no records yet. Ask Smith to add some — for example “keep track of orders”.</p>,
    },
    {
      title: kind === "metric" ? "Which number?" : "What should the chart measure?", ok: !!measure,
      body: <div className="space-y-1">{measures.map((m) => (
        <Choice key={m.key} name="m" checked={measure.key === m.key} onChange={() => setMeasure(m)}>{entity ? measureLabel(m, entity.name) : m.key}</Choice>))}</div>,
    },
  ];
  if (kind === "chart") {
    steps.push({
      title: "Group it by…", ok: !!dimension,
      body: groups.length ? <div className="space-y-1">{groups.map((f) => (
        <Choice key={f.name} name="d" checked={dimension?.field === f.name} onChange={() => setDimension(f.isDate ? { field: f.name, bucket: "month" } : { field: f.name })}>
          <span>{f.label || humanise(f.name)}</span>
          {f.isDate && dimension?.field === f.name && (
            <span className="mt-1 flex flex-wrap gap-1">{(["day", "week", "month", "quarter", "year"] as const).map((b) => (
              <button key={b} type="button" onClick={(e) => { e.preventDefault(); setDimension({ field: f.name, bucket: b }); }}
                className={cn("rounded border px-1.5 py-0.5 text-[11px]", dimension.bucket === b ? "border-primary bg-primary text-primary-foreground" : "border-border")}>per {b}</button>))}</span>
          )}
        </Choice>))}</div>
        : <p className="text-sm text-muted-foreground">{entity?.name} has nothing to group by yet — a status, a category or a date field. Ask Smith to add one, or add a number tile instead.</p>,
    });
    steps.push({
      title: "Only some of them?", ok: true,
      body: (
        <div className="space-y-2">
          <FilterEditor entity={entity} samples={doc.samples?.[entity?.name ?? ""] ?? []} value={filter} onChange={setFilter} />
          <p className="text-[11px] text-muted-foreground">Leave empty to include every {entity?.name.toLowerCase() ?? "record"}.</p>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <p className="mb-1 text-[11px] font-medium text-muted-foreground">Also split by</p>
              <select className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs" value={split ?? ""} onChange={(e) => setSplit(e.target.value || null)} aria-label="Also split by">
                <option value="">Nothing</option>
                {groups.filter((g) => g.name !== dimension?.field && !g.isDate).map((g) => <option key={g.name} value={g.name}>{g.label || humanise(g.name)}</option>)}
              </select>
            </div>
            <div>
              <p className="mb-1 text-[11px] font-medium text-muted-foreground">Order</p>
              <select className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="Order">
                <option value="auto">{dimension?.bucket ? "By date" : "Biggest first"}</option>
                <option value="biggest">Biggest first</option><option value="smallest">Smallest first</option><option value="name">By name</option>
              </select>
            </div>
          </div>
          <div>
            <p className="mb-1 text-[11px] font-medium text-muted-foreground">Show at most</p>
            <select className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs" value={limit ?? ""} onChange={(e) => setLimit(e.target.value ? Number(e.target.value) : null)} aria-label="Show at most">
              <option value="">Everything</option><option value="5">Top 5</option><option value="10">Top 10</option><option value="20">Top 20</option>
            </select>
          </div>
        </div>
      ),
    });
    steps.push({
      title: "How should it look?", ok: true,
      body: (
        <div>
          <div className="grid grid-cols-4 gap-1">{MARKS.map((m) => (
            <button key={m.value} type="button" onClick={() => setMark(m.value)}
              className={cn("rounded-md border p-2 text-xs", mark === m.value ? "border-primary bg-primary/5 font-medium" : "border-border hover:bg-muted")}>{m.label}</button>))}</div>
          {["bar", "area", "line"].includes(mark) && (
            <div className="mt-2 flex gap-4 text-xs">
              {mark !== "line" && <label className="flex items-center gap-1"><input type="checkbox" checked={stacked} onChange={(e) => setStacked(e.target.checked)} /> Stacked</label>}
              {mark === "bar" && <label className="flex items-center gap-1"><input type="checkbox" checked={horizontal} onChange={(e) => setHorizontal(e.target.checked)} /> Sideways</label>}
            </div>
          )}
        </div>
      ),
    });
  }
  if (kind === "metric") {
    steps.push({ title: "Only some of them?", ok: true, body: <div className="space-y-2"><FilterEditor entity={entity} samples={doc.samples?.[entity?.name ?? ""] ?? []} value={filter} onChange={setFilter} /><p className="text-[11px] text-muted-foreground">Leave empty to count every {entity?.name.toLowerCase() ?? "record"}.</p></div> });
  }
  steps.push({ title: "What should it be called?", ok: !!title, body: <Input value={label} placeholder={defaultTitle} onChange={(e) => setLabel(e.target.value)} aria-label="Title" /> });

  const last = step >= steps.length - 1;
  const summary = entity ? `${kind === "metric" ? "A number tile" : `A ${MARKS.find((m) => m.value === mark)?.label.toLowerCase() ?? mark} chart`}: “${title}” — ${measureLabel(measure, entity.name).toLowerCase()}${dimension ? ` by ${humanise(dimension.field).toLowerCase()}${dimension.bucket ? ` per ${dimension.bucket}` : ""}` : ""}, from the app's ${entity.name.toLowerCase()} records.` : "";

  const finish = async () => {
    if (!entity || !doc.model) return;
    setBusy(true);
    const spec: WidgetSpec = {
      label: title, kind, entity: entity.name, measures: [{ ...measure, label: measureLabel(measure, entity.name) }],
      dimensions: kind === "metric" ? [] : dimensions, unit: "number", size: kind === "metric" ? "sm" : "md",
      filter, sort: sortSpec, limit,
      ...(kind === "chart" ? { mark, stacked: stacked || dimensions.length > 1, horizontal } : {}),
    };
    let created: { id: string } | null = null;
    try {
      const out = await editorApi.createWidget(projectId, doc.page.id, spec);
      created = out.widget;
      const t = insertionTarget(doc.model, selection, def);
      const ops = widgetOps(doc.model, out.widget, t.afterId ? { afterId: t.afterId } : { parentId: t.parentId, index: t.index });
      const ok = await applyOps(ops, `Add ${kind === "metric" ? "number tile" : "chart"} “${title}”`);
      if (!ok) throw new Error("The page could not take the chart.");
      await reload();
      onClose();
    } catch (err) {
      const f = failureOf(err);
      toast.error(kind === "metric" ? "Couldn't add the number tile." : "Couldn't add the chart.", { description: f.message, duration: 8000 });
      if (created) { try { await editorApi.removeWidget(projectId, created.id); } catch { /* best effort */ } }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{steps[step]?.title ?? def.label}</DialogTitle>
          <DialogDescription>Step {step + 1} of {steps.length} — {def.description.toLowerCase()}. Drawn from the app's real data.</DialogDescription>
        </DialogHeader>
        <div className="max-h-[50vh] overflow-auto">{steps[step]?.body}</div>
        {entity && step > 0 && (
          <div className="rounded-md border border-border p-2">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Preview with sample data</p>
            <ChartPreview rows={preview} mark={kind === "metric" ? "metric" : mark} dimension={kind === "metric" ? null : dimension?.field ?? null} measureKey={measure.key} />
          </div>
        )}
        {summary && <p className="rounded-md bg-muted p-2 text-xs text-muted-foreground">You will get: {summary}</p>}
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" size="sm" onClick={() => (step ? setStep(step - 1) : onClose())} disabled={busy}>{step ? "Back" : "Cancel"}</Button>
          <div className="flex gap-2">
            {!last && <Button size="sm" variant="outline" disabled={!steps[step]?.ok} onClick={() => setStep(step + 1)}>Next</Button>}
            <Button size="sm" disabled={busy || !steps.every((s) => s.ok)} onClick={() => void finish()}>{busy ? "Adding…" : "Add it"}</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
