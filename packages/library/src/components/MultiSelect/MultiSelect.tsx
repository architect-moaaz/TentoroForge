"use client";

import * as React from "react";
import { z } from "zod";
import type { MultiSelectNode } from "@tentoroforge/schema";
import { useUrlState } from "../../style/useUrlState";

type Props = z.infer<typeof MultiSelectNode>["props"];

export function MultiSelect({
  name, label, placeholder = "Select…", options, selected,
  showSearch, maxSelectionLabel = 3,
}: Props) {
  const initialCsv = (selected ?? []).join(",");
  const [valueCsv, setValueCsv] = useUrlState(name, initialCsv);
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  const selectedSet = React.useMemo(() => new Set(valueCsv ? valueCsv.split(",") : []), [valueCsv]);

  const visibleOptions = React.useMemo(() => {
    if (!search.trim()) return options;
    const q = search.toLowerCase();
    return options.filter((o) =>
      o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
    );
  }, [options, search]);

  function toggle(val: string) {
    const next = new Set(selectedSet);
    if (next.has(val)) next.delete(val);
    else next.add(val);
    setValueCsv(Array.from(next).join(","));
  }

  function clear() {
    setValueCsv("");
  }

  const showSearchBox = showSearch ?? options.length > 8;

  const triggerLabel = (() => {
    if (selectedSet.size === 0) return placeholder;
    if (selectedSet.size > maxSelectionLabel) return `${selectedSet.size} selected`;
    return options
      .filter((o) => selectedSet.has(o.value))
      .map((o) => o.label)
      .join(", ");
  })();

  return (
    <div className="relative inline-block">
      {label && <label className="me-2 text-xs font-medium text-muted-foreground">{label}:</label>}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 min-w-[140px] items-center justify-between gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium hover:bg-muted/50"
      >
        <span className={selectedSet.size === 0 ? "text-muted-foreground" : ""}>{triggerLabel}</span>
        <span className="opacity-60">▾</span>
      </button>
      {open && (
        <div className="absolute start-0 top-full mt-1 min-w-[240px] rounded-md border border-border bg-popover shadow-md z-10">
          {showSearchBox && (
            <div className="border-b border-border p-2">
              <input
                type="text"
                placeholder="Search…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-7 w-full rounded border border-border bg-background px-2 text-xs"
                autoFocus
              />
            </div>
          )}
          <ul className="max-h-64 overflow-y-auto py-1">
            {visibleOptions.length === 0 && (
              <li className="px-3 py-2 text-xs text-muted-foreground">No options match.</li>
            )}
            {visibleOptions.map((opt) => {
              const checked = selectedSet.has(opt.value);
              return (
                <li key={opt.value}>
                  <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(opt.value)}
                      className="h-3.5 w-3.5 rounded border-border"
                    />
                    <span className={checked ? "font-medium text-foreground" : "text-muted-foreground"}>
                      {opt.label}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="flex items-center justify-between border-t border-border p-2">
            <button
              type="button"
              onClick={clear}
              disabled={selectedSet.size === 0}
              className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              Clear ({selectedSet.size})
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
