"use client";
/**
 * "Where does this come from?" — a value chosen by pointing (DATA-003): a
 * source the page already has, then which part of it, with an example of
 * what it will show. Never a typed expression.
 */
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { fieldChoices, pageSources, rowContext, sampleOf, type DataSource } from "./lib/data";
import type { PageDoc } from "./types";

const NONE = "__none__";
/** The source's own value — `fieldChoices` names it "" (no part to pick), and
 *  a Select item may not carry an empty value. Mapped here and back. */
const SELF = "__self__";

export interface DataChoice { source: DataSource; field: string }

export function DataPicker({ doc, nodeId, value, onChange, want, compact }: {
  doc: PageDoc;
  /** The element the value is for — its row, if it sits in a list, is offered first. */
  nodeId: string;
  value: DataChoice | null;
  onChange: (choice: DataChoice | null) => void;
  /** Narrow what is offered: a record's id for a workflow, any text, a number. */
  want?: "id" | "text" | "number";
  compact?: boolean;
}) {
  const row = rowContext(doc, nodeId);
  const sources = [...(row ? [row] : []), ...pageSources(doc)].filter((s) => {
    if (want === "id") return s.shape.kind === "record" || s.shape.kind === "row";
    return s.shape.kind !== "unknown" && s.shape.kind !== "context";
  });
  const source = value ? sources.find((s) => s.id === value.source.id) ?? value.source : null;
  const fields = source ? fieldChoices(doc, source).filter((f) => {
    if (want === "id") return false;
    if (want === "number") return /int|number|decimal|float|numeric/.test(f.type);
    return true;
  }) : [];
  const idOnly = want === "id";
  const example = source ? (idOnly ? `e.g. the ${source.entity?.name.toLowerCase() ?? "record"} shown` : value?.field !== undefined ? sampleOf(doc, source, value.field) : "") : "";

  return (
    <div className={compact ? "space-y-1" : "space-y-2"}>
      <div>
        {!compact && <Label className="mb-1 block text-[11px] font-medium text-muted-foreground">Where from</Label>}
        <Select value={source?.id ?? NONE} onValueChange={(v) => {
          const s = sources.find((x) => x.id === v);
          if (!s) { onChange(null); return; }
          const first = idOnly ? "id" : fieldChoices(doc, s).find((f) => want !== "number" || /int|number|decimal|float|numeric/.test(f.type))?.name ?? "";
          onChange({ source: s, field: first });
        }}>
          <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Choose where the value comes from" /></SelectTrigger>
          <SelectContent>
            {sources.map((s) => <SelectItem key={s.id} value={s.id}>{s.label}</SelectItem>)}
            {!sources.length && <SelectItem value={NONE} disabled>This page has no data of that kind yet</SelectItem>}
          </SelectContent>
        </Select>
      </div>
      {source && !idOnly && fields.length > 0 && (
        <div>
          {!compact && <Label className="mb-1 block text-[11px] font-medium text-muted-foreground">Which part</Label>}
          <Select value={value?.field === undefined ? "" : (value.field || SELF)}
                  onValueChange={(f) => onChange({ source, field: f === SELF ? "" : f })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Choose" /></SelectTrigger>
            <SelectContent>{fields.map((f) => <SelectItem key={f.name || SELF} value={f.name || SELF}>{f.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      )}
      {source?.via && <p className="text-[10px] text-muted-foreground">{source.via}</p>}
      {source?.row && <p className="text-[10px] text-muted-foreground">One row of the list this sits in</p>}
      {example && <p className="text-[10px] text-muted-foreground">Example: <span className="text-foreground">{example}</span></p>}
    </div>
  );
}
