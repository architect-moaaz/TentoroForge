"use client";
/**
 * The application's look, for the person who owns it: colours by the job
 * they do, the fonts, how rounded the corners are, how dense the screens are.
 * Every change is the Blueprint's design system changing, so every page
 * follows — the canvas at once, the running app on its next build.
 */
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

import { useEditorStore } from "./store";
import type { ThemeDoc } from "./types";

function ColorRow({ role, label, about, value, set, disabled, onChange }: {
  role: string; label: string; about: string; value: string | null; set: boolean; disabled: boolean; onChange: (v: string) => void;
}) {
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => setDraft(value ?? ""), [value]);
  const commit = (v: string) => { if (/^#[0-9a-fA-F]{6}$/.test(v) && v.toLowerCase() !== (value ?? "").toLowerCase()) onChange(v.toLowerCase()); };
  return (
    <div className="flex items-center gap-2 py-1" data-role={role}>
      <label className="relative h-7 w-7 shrink-0 cursor-pointer overflow-hidden rounded-md border border-border" style={{ background: value ?? "transparent" }} title={`Pick the ${label.toLowerCase()}`}>
        <input type="color" className="absolute inset-0 h-full w-full cursor-pointer opacity-0" value={value ?? "#000000"} disabled={disabled} aria-label={`${label} colour`}
          onChange={(e) => setDraft(e.target.value)} onBlur={(e) => commit(e.target.value)} />
      </label>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium">{label}{!set && <span className="ml-1 text-[10px] font-normal text-muted-foreground">(default)</span>}</div>
        <div className="truncate text-[10px] text-muted-foreground">{about}</div>
      </div>
      <Input className="h-7 w-[84px] font-mono text-[11px]" value={draft} disabled={disabled} aria-label={`${label} as hex`}
        onChange={(e) => setDraft(e.target.value)} onBlur={() => commit(draft)} onKeyDown={(e) => { if (e.key === "Enter") commit(draft); }} />
    </div>
  );
}

export function ThemePanel() {
  const theme = useEditorStore((s) => s.theme);
  const loading = useEditorStore((s) => s.themeLoading);
  const loadTheme = useEditorStore((s) => s.loadTheme);
  const saveTheme = useEditorStore((s) => s.saveTheme);
  const busy = useEditorStore((s) => s.busy) || loading;
  useEffect(() => { if (!theme) void loadTheme(); }, [theme, loadTheme]);

  if (!theme) return <p className="p-3 text-xs text-muted-foreground">{loading ? "Reading the application's look…" : "The application's look could not be read."}</p>;
  if (!theme.hasDesign) return <p className="p-3 text-xs text-muted-foreground">This application has no design system yet — the build authors it, and then it can be changed here.</p>;

  const groups = [...new Set(theme.colors.map((c) => c.group))];
  const setColor = (role: string, v: string) => void saveTheme({ colors: { [role]: v } });
  const font = (value: string, onCommit: (v: string) => void, label: string) => (
    <FontField value={value} suggestions={theme.fontSuggestions} disabled={busy} label={label} onCommit={onCommit} />
  );

  return (
    <div className="space-y-4 p-3 text-xs">
      {theme.personality && <p className="rounded-md bg-muted px-2 py-1.5 text-[11px] leading-snug text-muted-foreground">{theme.personality.slice(0, 220)}{theme.personality.length > 220 ? "…" : ""}</p>}
      {theme.warnings.length > 0 && (
        <div className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
          {theme.warnings.map((w) => <p key={w} className="flex gap-1"><AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />{w}</p>)}
        </div>
      )}
      {groups.map((g) => (
        <section key={g}>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{g}</h3>
          {theme.colors.filter((c) => c.group === g).map((c) => (
            <ColorRow key={c.role} role={c.role} label={c.label} about={c.about} value={c.value} set={c.set} disabled={busy} onChange={(v) => setColor(c.role, v)} />
          ))}
        </section>
      ))}
      <section className="space-y-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Type</h3>
        {font(theme.font, (v) => void saveTheme({ font: v }), "Font")}
        {font(theme.headingFont, (v) => void saveTheme({ headingFont: v }), "Heading font (blank: same as text)")}
        <div>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">Text size</div>
          <Select value={theme.baseSize || "default"} disabled={busy} onValueChange={(v) => void saveTheme({ baseSize: v === "default" ? "" : v })}>
            <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="default">Default</SelectItem>
              {["13px", "14px", "15px", "16px", "17px", "18px"].map((s) => <SelectItem key={s} value={s}>{s.replace("px", " px")}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </section>
      <section className="space-y-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Shape and space</h3>
        <div>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">Corners</div>
          <div className="flex gap-1">
            {theme.radiusChoices.map((r) => (
              <button key={r.value} type="button" disabled={busy} onClick={() => void saveTheme({ radius: r.value })} title={r.value}
                className={cn("flex h-9 flex-1 flex-col items-center justify-center border text-[10px]", theme.radius === r.value ? "border-primary bg-primary/10" : "border-border hover:bg-muted")} style={{ borderRadius: r.value }}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">Density</div>
          <div className="flex rounded-md bg-muted p-0.5" role="group" aria-label="Density">
            {(["compact", "comfortable", "spacious"] as const).map((d) => (
              <button key={d} type="button" disabled={busy} onClick={() => void saveTheme({ density: d })}
                className={cn("flex-1 rounded px-2 py-1 capitalize", theme.density === d ? "bg-background font-medium shadow-sm" : "text-muted-foreground")}>{d}</button>
            ))}
          </div>
        </div>
      </section>
      <p className="flex items-start gap-1 text-[10px] text-muted-foreground"><RotateCcw className="mt-0.5 h-3 w-3 shrink-0" /> Every page follows these. Undo is in the page history; the running app takes them on its next build.</p>
    </div>
  );
}

function FontField({ value, suggestions, disabled, label, onCommit }: { value: string; suggestions: string[]; disabled: boolean; label: string; onCommit: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!boxRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  const commit = (v: string) => { setDraft(v); setOpen(false); if (v.trim() !== value.trim()) onCommit(v.trim()); };
  return (
    <div ref={boxRef} className="relative">
      <div className="mb-1 text-[11px] font-medium text-muted-foreground">{label}</div>
      <Input className="h-8 text-xs" value={draft} disabled={disabled} aria-label={label} placeholder="Inter, Roboto, Georgia…"
        autoComplete="off" style={{ fontFamily: draft || undefined }}
        onFocus={() => setOpen(true)} onClick={() => setOpen(true)}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { if (draft.trim() !== value.trim()) onCommit(draft.trim()); }}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setOpen(false); }} />
      {open && suggestions.length > 0 && (
        <div className="absolute z-50 mt-1 max-h-48 w-full overflow-y-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-md">
          {suggestions.map((s) => (
            <button key={s} type="button" style={{ fontFamily: s }}
              className="flex w-full cursor-default items-center rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground"
              onMouseDown={(e) => e.preventDefault()} onClick={() => commit(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
