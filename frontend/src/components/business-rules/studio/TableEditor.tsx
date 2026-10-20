"use client";

// A decision table, edited as a sheet: the fields it reads on the left, the
// fields it sets on the right, one row per case. Cells are checked by the
// app's own engine (the server's findings mark the very cell); the rows the
// last test matched are lit, the one used most of all.

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Copy, HelpCircle, Plus, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  CELL_HELP, HIT_POLICIES, columnType, humanField, newKey,
  type Aggregation, type Finding, type HitPolicy, type TableColumn, type TableState,
} from "@/lib/rules-studio";
import type { CatalogueField } from "@/lib/blueprint-rules";

export function TableEditor({
  value,
  onChange,
  fields,
  findings,
  matched,
  used,
  disabled,
}: {
  value: TableState;
  onChange: (t: TableState) => void;
  fields: CatalogueField[];
  findings: Finding[];
  /** 1-based rows the last test matched, and the ones whose results were used. */
  matched?: number[];
  used?: number[];
  disabled?: boolean;
}) {
  const t = value;
  const set = (patch: Partial<TableState>) => onChange({ ...t, ...patch });
  const usedFields = new Set([...t.inputs, ...t.outputs].map((c) => c.field));
  const free = fields.filter((f) => !usedFields.has(f.name) && !["id", "createdAt", "updatedAt"].includes(f.name));

  // Findings by cell: "row:column" -> finding (errors before warnings).
  const byCell = useMemo(() => {
    const m = new Map<string, Finding>();
    for (const f of [...findings].sort((a, b) => (a.severity === "error" ? -1 : 1) - (b.severity === "error" ? -1 : 1))) {
      if (f.row && f.column && !m.has(`${f.row}:${f.column}`)) m.set(`${f.row}:${f.column}`, f);
    }
    return m;
  }, [findings]);
  const byRow = useMemo(() => {
    const m = new Map<number, Finding>();
    for (const f of findings) if (f.row && !f.column && !m.has(f.row)) m.set(f.row, f);
    return m;
  }, [findings]);

  const addColumn = (side: "inputs" | "outputs", fieldName: string) => {
    const f = fields.find((x) => x.name === fieldName);
    if (!f) return;
    const col: TableColumn = { key: newKey("col"), field: f.name, type: columnType(f.type),
                               values: f.enumValues?.length ? f.enumValues : undefined };
    const rows = t.rows.map((r) => side === "inputs" ? { ...r, inputs: [...r.inputs, "-"] } : { ...r, outputs: [...r.outputs, ""] });
    // A first column of a fresh table comes with a first row to fill in.
    const firstRow = !t.rows.length ? [{ key: newKey("row"), inputs: side === "inputs" ? ["-"] : [], outputs: side === "outputs" ? [""] : [] }] : [];
    set({ [side]: [...t[side], col], rows: [...rows, ...firstRow].map((r) => ({
      ...r,
      inputs: side === "inputs" ? r.inputs : r.inputs.length ? r.inputs : t.inputs.map(() => "-"),
      outputs: side === "outputs" ? r.outputs : r.outputs.length ? r.outputs : t.outputs.map(() => ""),
    })) } as Partial<TableState>);
  };
  const removeColumn = (side: "inputs" | "outputs", idx: number) => {
    set({
      [side]: t[side].filter((_, i) => i !== idx),
      rows: t.rows.map((r) => ({ ...r, [side]: r[side].filter((_, i) => i !== idx) })),
    } as Partial<TableState>);
  };
  const setCell = (ri: number, side: "inputs" | "outputs", ci: number, v: string) => {
    set({ rows: t.rows.map((r, i) => i !== ri ? r : { ...r, [side]: r[side].map((c, j) => (j === ci ? v : c)) }) });
  };
  const addRow = (at = t.rows.length) => {
    const row = { key: newKey("row"), inputs: t.inputs.map(() => "-"), outputs: t.outputs.map(() => "") };
    set({ rows: [...t.rows.slice(0, at), row, ...t.rows.slice(at)] });
  };
  const dupRow = (ri: number) => {
    const r = t.rows[ri];
    set({ rows: [...t.rows.slice(0, ri + 1), { ...r, key: newKey("row"), inputs: [...r.inputs], outputs: [...r.outputs] }, ...t.rows.slice(ri + 1)] });
  };
  const moveRow = (ri: number, by: number) => {
    const to = ri + by;
    if (to < 0 || to >= t.rows.length) return;
    const rows = [...t.rows];
    [rows[ri], rows[to]] = [rows[to], rows[ri]];
    set({ rows });
  };
  const policy = HIT_POLICIES.find((p) => p.id === t.hitPolicy) ?? HIT_POLICIES[1];

  const header = (c: TableColumn, side: "inputs" | "outputs", i: number) => (
    <th key={c.key} className={cn("min-w-[150px] border-b px-2 py-1.5 text-left align-bottom font-medium",
                                  side === "inputs" ? "bg-sky-50/70 dark:bg-sky-950/30" : "bg-emerald-50/70 dark:bg-emerald-950/30")}>
      <div className="flex items-center gap-1">
        <span className="truncate text-xs" title={c.field}>{humanField(c.field)}</span>
        <span className="rounded bg-background/70 px-1 text-[10px] text-muted-foreground">{c.values?.length ? `${c.values.length} choices` : c.type}</span>
        {!disabled && (
          <button type="button" onClick={() => removeColumn(side, i)} aria-label={`Remove ${c.field}`}
                  className="ml-auto text-muted-foreground hover:text-destructive"><X className="h-3 w-3" /></button>
        )}
      </div>
    </th>
  );

  const cell = (ri: number, side: "inputs" | "outputs", ci: number, c: TableColumn) => {
    const v = t.rows[ri][side][ci] ?? "";
    const f = byCell.get(`${ri + 1}:${c.label || c.field}`) ?? byCell.get(`${ri + 1}:${c.field}`);
    const listId = c.values?.length ? `vals_${c.key}` : undefined;
    return (
      <td key={c.key} className="border-b border-r p-0 align-top">
        <input
          value={v}
          disabled={disabled}
          onChange={(e) => setCell(ri, side, ci, e.target.value)}
          onFocus={(e) => { if (e.target.value === "-") e.target.select(); }}
          list={listId}
          placeholder={side === "inputs" ? "-" : c.values?.[0] ?? "value"}
          aria-label={`Row ${ri + 1}, ${c.field}`}
          aria-invalid={f?.severity === "error" || undefined}
          title={f?.message}
          className={cn(
            "h-9 w-full bg-transparent px-2 font-mono text-xs outline-none focus:bg-background focus:ring-2 focus:ring-inset focus:ring-primary/40",
            f?.severity === "error" && "bg-rose-50 text-rose-900 ring-1 ring-inset ring-rose-300 dark:bg-rose-950/40 dark:text-rose-200",
            f?.severity === "warning" && "bg-amber-50 dark:bg-amber-950/30",
          )}
        />
        {listId && (
          <datalist id={listId}>{c.values!.map((x) => <option key={x} value={x} />)}</datalist>
        )}
      </td>
    );
  };

  return (
    <div className="space-y-4" data-testid="table-editor">
      <div className="space-y-2">
        <p className="text-xs font-medium text-muted-foreground">When more than one row matches</p>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Hit policy">
          {HIT_POLICIES.filter((p) => p.forRecords).map((p) => (
            <button key={p.id} type="button" role="radio" aria-checked={t.hitPolicy === p.id} disabled={disabled}
                    onClick={() => set({ hitPolicy: p.id as HitPolicy, ...(p.id === "C" ? { aggregation: t.aggregation ?? "SUM" } : {}) })}
                    className={cn("rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                                  t.hitPolicy === p.id ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted")}>
              {p.name}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">{policy.says}</p>
        {t.hitPolicy === "C" && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Combine the matches by</span>
            {(["SUM", "COUNT", "MIN", "MAX"] as Aggregation[]).map((a) => {
              // A total fills number fields (smallest/largest: dates too).
              const fits = t.outputs.every((c) => c.type === "number" || ((a === "MIN" || a === "MAX") && c.type === "date"));
              return (
              <button key={a} type="button" disabled={disabled || !fits} onClick={() => set({ aggregation: a })}
                      title={fits ? undefined : "Only for fields that hold a number"}
                      className={cn("rounded border px-2 py-0.5 disabled:opacity-40", t.aggregation === a ? "border-primary bg-primary/10 font-medium" : "hover:bg-muted")}>
                {{ SUM: "adding up", COUNT: "counting", MIN: "the smallest", MAX: "the largest" }[a]}
              </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <FieldPicker label="Field it reads" fields={free} onPick={(f) => addColumn("inputs", f)} disabled={disabled} tone="in" />
        <FieldPicker label="Field it sets" fields={free} onPick={(f) => addColumn("outputs", f)} disabled={disabled} tone="out" />
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="sm" className="ml-auto h-8 gap-1 text-xs"><HelpCircle className="h-3.5 w-3.5" /> How to fill a cell</Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-80">
            <p className="mb-2 text-xs font-medium">A cell of a field it reads matches when:</p>
            <ul className="space-y-1">
              {CELL_HELP.map((h) => (
                <li key={h.example} className="flex gap-3 text-xs">
                  <code className="min-w-[110px] rounded bg-muted px-1.5 py-0.5">{h.example}</code>
                  <span className="text-muted-foreground">{h.means}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">A cell of a field it sets is a value, or a formula like <code>amount * 0.1</code>.</p>
          </PopoverContent>
        </Popover>
      </div>

      {t.inputs.length + t.outputs.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Pick a field the table reads (like <em>amount</em>) and a field it sets (like <em>approver</em>) — then one row per case.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="w-10 border-b bg-muted/40" />
                {t.inputs.length > 0 && <th colSpan={t.inputs.length} className="border-b bg-sky-50/70 px-2 py-1 text-left dark:bg-sky-950/30">When</th>}
                {t.outputs.length > 0 && <th colSpan={t.outputs.length} className="border-b bg-emerald-50/70 px-2 py-1 text-left dark:bg-emerald-950/30">Then set</th>}
                <th className="border-b bg-muted/40 px-2 py-1 text-left">Note</th>
                <th className="w-28 border-b bg-muted/40" />
              </tr>
              <tr>
                <th className="border-b bg-muted/40 text-xs text-muted-foreground">#</th>
                {t.inputs.map((c, i) => header(c, "inputs", i))}
                {t.outputs.map((c, i) => header(c, "outputs", i))}
                <th className="border-b bg-muted/40" />
                <th className="border-b bg-muted/40" />
              </tr>
            </thead>
            <tbody>
              {t.rows.map((r, ri) => {
                const n = ri + 1;
                const lit = used?.includes(n) ? "used" : matched?.includes(n) ? "matched" : null;
                const rowFinding = byRow.get(n);
                return (
                  <tr key={r.key} data-row={n} data-lit={lit ?? undefined}
                      className={cn(lit === "used" && "bg-emerald-100/60 dark:bg-emerald-900/30",
                                    lit === "matched" && "bg-emerald-50/50 dark:bg-emerald-950/20")}>
                    <td className="border-b border-r text-center text-xs text-muted-foreground" title={rowFinding?.message}>
                      <span className={cn(rowFinding && (rowFinding.severity === "error" ? "font-bold text-rose-600" : "font-bold text-amber-600"))}>{n}</span>
                    </td>
                    {t.inputs.map((c, ci) => cell(ri, "inputs", ci, c))}
                    {t.outputs.map((c, ci) => cell(ri, "outputs", ci, c))}
                    <td className="border-b border-r p-0">
                      <input value={r.note ?? ""} disabled={disabled} placeholder="why" aria-label={`Row ${n}, note`}
                             onChange={(e) => set({ rows: t.rows.map((x, i) => (i === ri ? { ...x, note: e.target.value } : x)) })}
                             className="h-9 w-full min-w-[120px] bg-transparent px-2 text-xs outline-none focus:bg-background" />
                    </td>
                    <td className="border-b px-1">
                      {!disabled && (
                        <div className="flex items-center justify-end gap-0.5 text-muted-foreground">
                          <button type="button" aria-label={`Move row ${n} up`} onClick={() => moveRow(ri, -1)} disabled={ri === 0}
                                  className="rounded p-1 hover:bg-muted disabled:opacity-30"><ArrowUp className="h-3.5 w-3.5" /></button>
                          <button type="button" aria-label={`Move row ${n} down`} onClick={() => moveRow(ri, 1)} disabled={ri === t.rows.length - 1}
                                  className="rounded p-1 hover:bg-muted disabled:opacity-30"><ArrowDown className="h-3.5 w-3.5" /></button>
                          <button type="button" aria-label={`Duplicate row ${n}`} onClick={() => dupRow(ri)}
                                  className="rounded p-1 hover:bg-muted"><Copy className="h-3.5 w-3.5" /></button>
                          <button type="button" aria-label={`Delete row ${n}`} onClick={() => set({ rows: t.rows.filter((_, i) => i !== ri) })}
                                  className="rounded p-1 hover:bg-muted hover:text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!disabled && (
            <button type="button" onClick={() => addRow()}
                    className="flex w-full items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground hover:bg-muted/50 hover:text-foreground">
              <Plus className="h-3.5 w-3.5" /> Add a row
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function FieldPicker({ label, fields, onPick, disabled, tone }: {
  label: string; fields: CatalogueField[]; onPick: (f: string) => void; disabled?: boolean; tone: "in" | "out";
}) {
  // Picked: closed, and the new column's first cell takes the typing — focus
  // used to go back to this button after the person had clicked into a cell,
  // so what they typed went nowhere.
  const [open, setOpen] = useState(false);
  const pick = (name: string) => {
    onPick(name);
    setOpen(false);
    setTimeout(() => document.querySelector<HTMLInputElement>(
      `[data-testid=table-editor] input[aria-label="Row 1, ${name}"]`)?.focus(), 60);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled || !fields.length}
                className={cn("h-8 gap-1 text-xs", tone === "in" ? "border-sky-300 text-sky-800 dark:text-sky-300" : "border-emerald-300 text-emerald-800 dark:text-emerald-300")}>
          <Plus className="h-3.5 w-3.5" /> {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-1" onCloseAutoFocus={(e) => e.preventDefault()}>
        <ul className="max-h-72 overflow-y-auto">
          {fields.map((f) => (
            <li key={f.name}>
              <button type="button" onClick={() => pick(f.name)}
                      className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-muted">
                <span>{humanField(f.name)}</span>
                <span className="text-[10px] text-muted-foreground">{f.type === "enum" ? `${f.enumValues.length} choices` : f.type}</span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

