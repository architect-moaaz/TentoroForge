"use client";
/**
 * The settings of a chart on the page: what it shows and how it is drawn.
 * These edit the widget in the Blueprint (the chart's definition), not the
 * page's code; the page rebuilds from the new definition. Removing a chart
 * takes its card and the data it loaded off the page, then retires the widget.
 */
import { useState } from "react";
import { AlertCircle, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

import { editorApi, failureOf } from "./api";
import { groupableFields, numericFields } from "./ChartDialog";
import { ChartPreview, FilterEditor } from "./DataMapping";
import { sampleQuery } from "./lib/data";
import { MARKS, humanise, measureLabel, widgetOfNode, widgetRemovalOps } from "./lib/templates";
import { useEditorStore } from "./store";
import type { ModelNode, PageDoc, WidgetMeasure, WidgetRef, WidgetSpec } from "./types";

const NONE = "__none__";

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <Label className="mb-1 block text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
      {help && <p className="mt-1 text-[10px] text-muted-foreground">{help}</p>}
    </div>
  );
}

export function ChartSettings({ node, doc }: { node: ModelNode; doc: PageDoc }) {
  const projectId = useEditorStore((s) => s.projectId)!;
  const reload = useEditorStore((s) => s.reload);
  const loadFrame = useEditorStore((s) => s.loadFrame);
  const applyOps = useEditorStore((s) => s.applyOps);
  const busy = useEditorStore((s) => s.busy);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState<string | null>(null);
  const widget = widgetOfNode(node, doc.widgets);
  if (!widget) {
    return <p className="px-3 py-2 text-[11px] text-muted-foreground">This chart's definition could not be found — ask Smith about it.</p>;
  }
  // A metric's query carries no `dimensions` (and may carry no measures yet):
  // read as empty, never as undefined — selecting a KPI tile crashed the editor.
  const query = widget.source.op === "query" ? widget.source as Extract<WidgetRef["source"], { op: "query" }> : null;
  const src = query ? { ...query, measures: query.measures ?? [], dimensions: query.dimensions ?? [] } : null;
  const entity = doc.entities.find((e) => e.name === widget.source.entity) ?? null;
  const measure = src?.measures[0];
  const dimension = src?.dimensions[0] ?? null;

  const change = async (spec: WidgetSpec) => {
    setSaving(true);
    setError(null);
    try {
      const out = await editorApi.updateWidget(projectId, widget.id, spec, doc.revision);
      await reload();
      if (!out.renamed) await loadFrame(undefined, { fresh: true });
    } catch (err) {
      const f = failureOf(err);
      setError(f.message);
      toast.error("Couldn't change the chart.", { description: f.message, duration: 8000 });
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    const ok = await applyOps(widgetRemovalOps(node, widget), `Remove chart “${widget.label}”`, { reselect: () => (node.parent ? [node.parent] : []) });
    if (!ok) return;
    try { await editorApi.removeWidget(projectId, widget.id); await reload(); }
    catch (err) { toast.warning("The chart is off the page, but its definition could not be retired.", { description: failureOf(err).message }); }
  };

  const measures: WidgetMeasure[] = entity ? [{ key: "count", aggregation: "count" },
    ...numericFields(entity).flatMap((f): WidgetMeasure[] => [{ key: `total_${f.name}`, aggregation: "sum", field: f.name }, { key: `average_${f.name}`, aggregation: "avg", field: f.name }])] : [];
  const measureId = measure ? `${measure.aggregation}:${measure.field ?? ""}` : NONE;
  const groups = entity ? groupableFields(entity) : [];
  const disabled = saving || busy;
  const split = src?.dimensions[1] ?? null;
  const filter = (src?.filter ?? {}) as Record<string, string | string[] | number | boolean>;
  const preview = entity && src ? sampleQuery(doc.samples?.[entity.name] ?? [], { measures: src.measures, dimensions: widget.kind === "chart" ? src.dimensions : [], filter, sort: src.sort ?? null, limit: src.limit ?? null }) : [];
  const sortValue = !src?.sort ? "auto" : src.sort.by === measure?.key ? (src.sort.order === "asc" ? "smallest" : "biggest") : "name";

  return (
    <div className="px-3 pb-2">
      {error && <p className="mb-2 flex items-start gap-1 rounded bg-destructive/10 p-2 text-[11px] text-destructive"><AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />{error}</p>}
      <Field label="Title">
        <Input className="h-8 text-xs" value={labelDraft ?? widget.label} disabled={disabled} aria-label="Chart title"
          onChange={(e) => setLabelDraft(e.target.value)}
          onBlur={() => { if (labelDraft != null && labelDraft.trim() && labelDraft !== widget.label) void change({ label: labelDraft.trim() }); setLabelDraft(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      </Field>
      <Field label="Show as">
        <Select value={widget.kind === "chart" ? "chart" : "metric"} disabled={disabled} onValueChange={(v) => void change(v === "metric" ? { kind: "metric", dimensions: [] } : { kind: "chart", mark: widget.chart?.mark ?? "bar", dimensions: dimension ? [dimension] : groups[0] ? [{ field: groups[0].name, ...(groups[0].isDate ? { bucket: "month" as const } : {}) }] : [] })}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="chart">A chart</SelectItem><SelectItem value="metric">One number</SelectItem></SelectContent>
        </Select>
      </Field>
      {widget.kind === "chart" && (
        <>
          <Field label="Chart type">
            <Select value={widget.chart?.mark ?? "bar"} disabled={disabled} onValueChange={(v) => void change({ mark: v as WidgetSpec["mark"] })}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>{MARKS.map((m) => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          {["bar", "area", "line"].includes(widget.chart?.mark ?? "bar") && (
            <div className="mb-3 flex gap-4 text-xs">
              {widget.chart?.mark !== "line" && <label className="flex items-center gap-2"><Switch checked={!!widget.chart?.stacked} disabled={disabled} onCheckedChange={(v) => void change({ stacked: v })} /> Stacked</label>}
              {widget.chart?.mark === "bar" && <label className="flex items-center gap-2"><Switch checked={!!widget.chart?.horizontal} disabled={disabled} onCheckedChange={(v) => void change({ horizontal: v })} /> Sideways</label>}
            </div>
          )}
        </>
      )}
      {entity && (
        <Field label={widget.kind === "chart" ? "What it measures" : "Which number"}>
          <Select value={measureId} disabled={disabled} onValueChange={(v) => { const m = measures.find((x) => `${x.aggregation}:${x.field ?? ""}` === v); if (m) void change({ measures: [{ ...m, label: measureLabel(m, entity.name) }] }); }}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Choose" /></SelectTrigger>
            <SelectContent>{measures.map((m) => <SelectItem key={`${m.aggregation}:${m.field ?? ""}`} value={`${m.aggregation}:${m.field ?? ""}`}>{measureLabel(m, entity.name)}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      )}
      {entity && widget.kind === "chart" && (
        <Field label="Grouped by">
          <div className="flex gap-1">
            <Select value={dimension?.field ?? NONE} disabled={disabled} onValueChange={(v) => { const f = groups.find((x) => x.name === v); if (f) void change({ dimensions: [f.isDate ? { field: f.name, bucket: dimension?.bucket ?? "month" } : { field: f.name }] }); }}>
              <SelectTrigger className="h-8 flex-1 text-xs"><SelectValue placeholder="Choose" /></SelectTrigger>
              <SelectContent>{groups.map((f) => <SelectItem key={f.name} value={f.name}>{f.label || humanise(f.name)}</SelectItem>)}</SelectContent>
            </Select>
            {dimension && groups.find((g) => g.name === dimension.field)?.isDate && (
              <Select value={dimension.bucket ?? "month"} disabled={disabled} onValueChange={(v) => void change({ dimensions: [{ field: dimension.field, bucket: v as "day" | "week" | "month" | "quarter" | "year" }] })}>
                <SelectTrigger className="h-8 w-28 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{(["day", "week", "month", "quarter", "year"] as const).map((b) => <SelectItem key={b} value={b}>per {b}</SelectItem>)}</SelectContent>
              </Select>
            )}
          </div>
        </Field>
      )}
      {entity && widget.kind === "chart" && dimension && (
        <Field label="Also split by">
          <Select value={split?.field ?? NONE} disabled={disabled} onValueChange={(v) => void change({ dimensions: v === NONE ? [dimension] : [dimension, { field: v }], stacked: v !== NONE ? true : widget.chart?.stacked })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Nothing</SelectItem>
              {groups.filter((g) => g.name !== dimension.field && !g.isDate).map((g) => <SelectItem key={g.name} value={g.name}>{g.label || humanise(g.name)}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
      )}
      {entity && (
        <Field label="Only include">
          <FilterEditor entity={entity} samples={doc.samples?.[entity.name] ?? []} value={filter} disabled={disabled} onChange={(next) => void change({ filter: next })} />
        </Field>
      )}
      {widget.kind === "chart" && measure && (
        <Field label="Order">
          <Select value={sortValue} disabled={disabled} onValueChange={(v) => void change({ sort: v === "auto" ? null : v === "name" && dimension ? { by: dimension.field, order: "asc" } : { by: measure.key, order: v === "smallest" ? "asc" : "desc" } })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="auto">{dimension?.bucket ? "By date" : "Biggest first"}</SelectItem><SelectItem value="biggest">Biggest first</SelectItem><SelectItem value="smallest">Smallest first</SelectItem><SelectItem value="name">By name</SelectItem></SelectContent>
          </Select>
        </Field>
      )}
      {entity && measure && (
        <div className="mb-3 rounded-md border border-border p-2">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">With sample data</p>
          <ChartPreview rows={preview} mark={widget.kind === "chart" ? widget.chart?.mark ?? "bar" : "metric"} dimension={widget.kind === "chart" ? dimension?.field ?? null : null} measureKey={measure.key} />
        </div>
      )}
      {widget.kind === "chart" && (
        <Field label="Show at most" help="Leave empty to show everything.">
          <Input className="h-8 text-xs" type="number" min={1} max={1000} defaultValue={src?.limit ?? ""} disabled={disabled} aria-label="Show at most"
            onBlur={(e) => { const n = Number(e.target.value); if ((n || null) !== (src?.limit ?? null)) void change({ limit: n ? n : null }); }} />
        </Field>
      )}
      <Field label="Shown as">
        <Select value={widget.unit} disabled={disabled} onValueChange={(v) => void change({ unit: v as WidgetRef["unit"] })}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="number">Plain numbers</SelectItem><SelectItem value="currency">Money</SelectItem>
            <SelectItem value="percent">Percentages</SelectItem><SelectItem value="duration">Durations</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="Description" help="Shown under the title.">
        <Input className="h-8 text-xs" defaultValue={widget.description} disabled={disabled} aria-label="Description"
          onBlur={(e) => { if (e.target.value !== widget.description) void change({ description: e.target.value }); }} />
      </Field>
      <Button size="sm" variant="ghost" className="h-7 text-xs text-destructive" disabled={disabled} onClick={() => void remove()}><Trash2 className="h-3 w-3" /> Remove this chart from the page</Button>
    </div>
  );
}
