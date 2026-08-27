"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ComboboxPropsType } from "./Combobox.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface ComboboxProps extends ComboboxPropsType {
  style?: StyleSlotT;
  value?: string;
  onChange?: (value: string) => void;
}

export function Combobox({ name, label, options = [], placeholder, filterable = true, style, value, onChange }: ComboboxProps) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [active, setActive] = React.useState(0);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const selectedLabel = options.find((o) => o.value === value)?.label ?? "";
  const filtered = filterable && query ? options.filter((o) => o.label.toLowerCase().includes(query.toLowerCase())) : options;
  const pick = (v: string) => { onChange?.(v); setOpen(false); setQuery(""); };

  return (
    <div className="relative flex flex-col gap-1" ref={ref} data-combobox="" style={resolveStyle(style)} {...useMotion(style?.motion)}>
      {label && <label className="text-sm font-medium text-foreground">{label}</label>}
      <input
        role="combobox" aria-expanded={open} name={name} placeholder={placeholder ?? selectedLabel ?? "Select…"}
        value={open ? query : selectedLabel}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          else if (e.key === "Enter" && filtered[active]) { e.preventDefault(); pick(filtered[active].value); }
          else if (e.key === "Escape") setOpen(false);
        }}
        className="rounded-md border border-input bg-transparent px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
      {open && (
        <ul role="listbox" className="absolute top-full z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border border-input bg-white py-1 shadow-md">
          {filtered.length === 0 ? (
            <li className="px-3 py-1.5 text-sm text-muted-foreground">No matches</li>
          ) : filtered.map((o, i) => (
            <li key={o.value} role="option" aria-selected={value === o.value}
              onMouseDown={(e) => { e.preventDefault(); pick(o.value); }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-1.5 text-sm ${i === active ? "bg-muted" : ""} ${value === o.value ? "font-medium" : ""}`}>
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
