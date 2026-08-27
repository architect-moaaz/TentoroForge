"use client";

import * as React from "react";
import { z } from "zod";
import type { DateRangePickerNode } from "@tentoroforge/schema";
import { useUrlState } from "../../style/useUrlState";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";

type Props = z.infer<typeof DateRangePickerNode>["props"];

const PRESET_LABELS: Record<string, string> = {
  "today":             "Today",
  "yesterday":         "Yesterday",
  "last-7-days":       "Last 7 days",
  "last-30-days":      "Last 30 days",
  "quarter-to-date":   "Quarter to date",
  "year-to-date":      "Year to date",
  "custom":            "Custom range",
};

const DEFAULT_PRESETS: NonNullable<Props["presets"]> = [
  "last-7-days", "last-30-days", "quarter-to-date", "year-to-date", "custom",
];

type PresetItem = { value: string; label: string };

// Presets may arrive as bare enum strings (schema contract) OR as { label, value }
// objects (some generated app schemas). Normalize both — and drop anything else —
// into a stable { value, label } list so we never render a raw object as a child.
function normalizePresets(presets: unknown): PresetItem[] {
  const list = Array.isArray(presets) ? presets : DEFAULT_PRESETS;
  const items: PresetItem[] = [];
  for (const p of list) {
    if (typeof p === "string") {
      items.push({ value: p, label: PRESET_LABELS[p] ?? p });
    } else if (p && typeof p === "object") {
      const value = (p as any).value;
      if (typeof value === "string") {
        const label = (p as any).label;
        items.push({
          value,
          label: typeof label === "string" ? label : PRESET_LABELS[value] ?? value,
        });
      }
    }
  }
  return items;
}

function formatDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function presetToRange(preset: string): { start: string; end: string } | null {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  switch (preset) {
    case "today":
      return { start: formatDate(today), end: formatDate(today) };
    case "yesterday":
      return { start: formatDate(yesterday), end: formatDate(yesterday) };
    case "last-7-days": {
      const start = new Date(today);
      start.setDate(today.getDate() - 6);
      return { start: formatDate(start), end: formatDate(today) };
    }
    case "last-30-days": {
      const start = new Date(today);
      start.setDate(today.getDate() - 29);
      return { start: formatDate(start), end: formatDate(today) };
    }
    case "quarter-to-date": {
      const q = Math.floor(today.getMonth() / 3);
      const start = new Date(today.getFullYear(), q * 3, 1);
      return { start: formatDate(start), end: formatDate(today) };
    }
    case "year-to-date": {
      const start = new Date(today.getFullYear(), 0, 1);
      return { start: formatDate(start), end: formatDate(today) };
    }
    default:
      return null;
  }
}

export function DateRangePicker({
  name, label, startDate, endDate, presets, minDate, maxDate,
}: Props) {
  const [start, setStart] = useUrlState(`${name}_start`, startDate ?? "");
  const [end, setEnd] = useUrlState(`${name}_end`, endDate ?? "");
  const presetItems = React.useMemo(() => normalizePresets(presets), [presets]);
  const radiusScale = useRadiusScale();
  const [open, setOpen] = React.useState(false);
  const [activePreset, setActivePreset] = React.useState<string>("custom");

  const display = React.useMemo(() => {
    if (!start && !end) return "Any date";
    if (start === end && start) return start;
    if (start && end) return `${start} → ${end}`;
    if (start) return `From ${start}`;
    return `Until ${end}`;
  }, [start, end]);

  function applyPreset(preset: string) {
    setActivePreset(preset);
    if (preset === "custom") return;  // keep dropdown open for manual date input
    const range = presetToRange(preset);
    if (range) {
      setStart(range.start);
      setEnd(range.end);
      setOpen(false);
    }
  }

  function clear() {
    setStart("");
    setEnd("");
    setActivePreset("custom");
    setOpen(false);
  }

  return (
    <div className="relative inline-block">
      {label && (
        <label className="mr-2 text-xs font-medium text-muted-foreground">{label}:</label>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex h-8 items-center gap-1.5 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-card px-2.5 text-xs font-medium hover:bg-muted/50`}
      >
        <span>{display}</span>
        <span className="opacity-60">▾</span>
      </button>
      {open && (
        <div className={`absolute left-0 top-full mt-1 w-72 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-popover p-3 shadow-md z-10`}>
          <ul className="mb-3 space-y-1">
            {presetItems.map((p) => (
              <li key={p.value}>
                <button
                  type="button"
                  onClick={() => applyPreset(p.value)}
                  className={`block w-full rounded px-2 py-1 text-left text-xs hover:bg-muted ${activePreset === p.value ? "bg-muted font-semibold" : ""}`}
                >
                  {p.label}
                </button>
              </li>
            ))}
          </ul>
          {activePreset === "custom" && (
            <div className="space-y-2 border-t border-border pt-3">
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">From</label>
                <input
                  type="date"
                  value={start}
                  min={minDate}
                  max={maxDate}
                  onChange={(e) => setStart(e.target.value)}
                  className="h-8 w-full rounded border border-border bg-background px-2 text-xs"
                />
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-muted-foreground mb-1">To</label>
                <input
                  type="date"
                  value={end}
                  min={start || minDate}
                  max={maxDate}
                  onChange={(e) => setEnd(e.target.value)}
                  className="h-8 w-full rounded border border-border bg-background px-2 text-xs"
                />
              </div>
            </div>
          )}
          <div className="mt-3 flex justify-between border-t border-border pt-2">
            <button
              type="button"
              onClick={clear}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
