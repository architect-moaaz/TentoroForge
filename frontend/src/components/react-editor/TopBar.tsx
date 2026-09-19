"use client";
import { useState } from "react";
import {
  Check, ClipboardCheck, Code2, Eye, History, Loader2, Monitor, MousePointer2, PanelLeft, PanelRight,
  Pencil, Play, Redo2, RotateCcw, Smartphone, SquareDashedMousePointer, Tablet, Undo2, X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { usePreview } from "@/hooks/usePreview";
import { cn } from "@/lib/utils";

import { BREAKPOINTS } from "./lib/classes";
import { saveLabel, useEditorStore } from "./store";
import type { Device } from "./types";

const DEVICES: { key: Exclude<Device, "custom">; label: string; icon: typeof Monitor }[] = [
  { key: "desktop", label: "Desktop", icon: Monitor },
  { key: "tablet", label: "Tablet", icon: Tablet },
  { key: "mobile", label: "Phone", icon: Smartphone },
];

function Seg({ active, onClick, title, children, disabled }: { active?: boolean; onClick: () => void; title: string; children: React.ReactNode; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} title={title} aria-label={title} aria-pressed={active} disabled={disabled}
      className={cn("inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium transition-colors",
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
        disabled && "opacity-40")}>
      {children}
    </button>
  );
}

export function TopBar({ preview }: { preview: ReturnType<typeof usePreview> }) {
  const doc = useEditorStore((s) => s.doc);
  const saveState = useEditorStore((s) => s.saveState);
  const saveError = useEditorStore((s) => s.saveError);
  const undoStack = useEditorStore((s) => s.undoStack);
  const redoStack = useEditorStore((s) => s.redoStack);
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const busy = useEditorStore((s) => s.busy);
  const mode = useEditorStore((s) => s.mode);
  const setMode = useEditorStore((s) => s.setMode);
  const previewApp = useEditorStore((s) => s.previewApp);
  const setPreviewApp = useEditorStore((s) => s.setPreviewApp);
  const regionSelect = useEditorStore((s) => s.regionSelect);
  const setRegionSelect = useEditorStore((s) => s.setRegionSelect);
  const viewLevel = useEditorStore((s) => s.viewLevel);
  const setViewLevel = useEditorStore((s) => s.setViewLevel);
  const device = useEditorStore((s) => s.device);
  const setDevice = useEditorStore((s) => s.setDevice);
  const setCustomWidth = useEditorStore((s) => s.setCustomWidth);
  const landscape = useEditorStore((s) => s.landscape);
  const setLandscape = useEditorStore((s) => s.setLandscape);
  const frameWidth = useEditorStore((s) => s.frameWidth);
  const leftOpen = useEditorStore((s) => s.leftOpen);
  const rightOpen = useEditorStore((s) => s.rightOpen);
  const setLeftOpen = useEditorStore((s) => s.setLeftOpen);
  const setRightOpen = useEditorStore((s) => s.setRightOpen);
  const setShowCode = useEditorStore((s) => s.setShowCode);
  const setShowHistory = useEditorStore((s) => s.setShowHistory);
  const setShowReadiness = useEditorStore((s) => s.setShowReadiness);
  const runCheck = useEditorStore((s) => s.runCheck);
  const [widthDraft, setWidthDraft] = useState<string | null>(null);

  const save = saveLabel(saveState, saveError);
  const width = frameWidth();
  const bp = BREAKPOINTS.slice().reverse().find((b) => width >= b.minWidth);

  return (
    <div className="flex h-11 shrink-0 items-center gap-1 overflow-hidden border-b border-border bg-card px-2">
      <Seg active={leftOpen} onClick={() => setLeftOpen(!leftOpen)} title="Show or hide the left panel (⌘/)"><PanelLeft className="h-3.5 w-3.5" /></Seg>
      <div className="mx-1 min-w-0 max-w-[14rem]">
        <div className="truncate text-sm font-semibold leading-tight">{doc?.page.name ?? "Editor"}</div>
        <div className="truncate text-[11px] leading-tight text-muted-foreground">{doc?.page.route ?? ""}</div>
      </div>

      <div className={cn("ml-2 flex items-center gap-1 rounded-md px-2 py-0.5 text-xs",
        save.tone === "ok" && "text-emerald-600", save.tone === "busy" && "text-muted-foreground", save.tone === "bad" && "bg-destructive/10 text-destructive")}
        role="status" aria-live="polite">
        {save.tone === "busy" ? <Loader2 className="h-3 w-3 animate-spin" /> : save.tone === "ok" ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
        <span className="max-w-[16rem] truncate">{save.text}</span>
      </div>

      <div className="mx-1 h-5 w-px bg-border" />
      <Seg onClick={() => void undo()} title={undoStack.length ? `Undo ${undoStack[undoStack.length - 1].label} (⌘Z)` : "Nothing to undo"} disabled={!undoStack.length || busy}><Undo2 className="h-3.5 w-3.5" /></Seg>
      <Seg onClick={() => void redo()} title={redoStack.length ? `Redo ${redoStack[redoStack.length - 1].label} (⇧⌘Z)` : "Nothing to redo"} disabled={!redoStack.length || busy}><Redo2 className="h-3.5 w-3.5" /></Seg>

      <div className="mx-1 h-5 w-px bg-border" />
      <div className="flex items-center rounded-md bg-muted p-0.5" role="group" aria-label="Design or preview">
        <Seg active={mode === "design"} onClick={() => setMode("design")} title="Design: click to select and change things"><Pencil className="h-3.5 w-3.5" /><span className="hidden xl:inline">Design</span></Seg>
        <Seg active={mode === "preview" && !previewApp} onClick={() => { setPreviewApp(false); setMode("preview"); }} title="Preview this page: use it as people will (⌘P)"><Eye className="h-3.5 w-3.5" /><span className="hidden xl:inline">Preview</span></Seg>
        <Seg active={previewApp} onClick={() => setPreviewApp(true)} title="Preview the whole application from its first page"><Play className="h-3.5 w-3.5" /><span className="hidden xl:inline">App</span></Seg>
      </div>
      {mode === "design" && (
        <Seg active={regionSelect} onClick={() => setRegionSelect(!regionSelect)} title="Select a region: drag a box around several things">
          {regionSelect ? <SquareDashedMousePointer className="h-3.5 w-3.5" /> : <MousePointer2 className="h-3.5 w-3.5" />}
        </Seg>
      )}

      <div className="mx-1 h-5 w-px bg-border" />
      <div className="flex items-center gap-0.5" role="group" aria-label="Screen size">
        {DEVICES.map((d) => (
          <Seg key={d.key} active={device === d.key} onClick={() => setDevice(d.key)} title={d.label}><d.icon className="h-3.5 w-3.5" /></Seg>
        ))}
        <Input aria-label="Custom width in pixels" className="h-7 w-16 px-1.5 text-center text-xs tabular-nums" inputMode="numeric"
          value={widthDraft ?? String(width)} onChange={(e) => setWidthDraft(e.target.value)}
          onBlur={() => { if (widthDraft != null) { const n = Number(widthDraft); if (n) setCustomWidth(n); setWidthDraft(null); } }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
        {device !== "desktop" && device !== "custom" && (
          <Seg active={landscape} onClick={() => setLandscape(!landscape)} title="Turn the device sideways"><RotateCcw className="h-3.5 w-3.5" /></Seg>
        )}
        <span className="ml-1 hidden whitespace-nowrap text-[11px] text-muted-foreground 2xl:inline" title="The responsive size the app uses at this width">
          {width}px · {bp?.label ?? "All screens"}
        </span>
      </div>

      <div className="flex-1" />

      <div className="flex items-center rounded-md bg-muted p-0.5" role="group" aria-label="How much to show">
        <Seg active={viewLevel === "simple"} onClick={() => setViewLevel("simple")} title="Simple: only what you need">Simple</Seg>
        <Seg active={viewLevel === "advanced"} onClick={() => setViewLevel("advanced")} title="Advanced: every setting, and the code">Advanced</Seg>
      </div>
      <div className="mx-1 h-5 w-px bg-border" />
      <Seg onClick={() => setShowHistory(true)} title="Version history"><History className="h-3.5 w-3.5" /></Seg>
      {viewLevel === "advanced" && <Seg onClick={() => setShowCode(true)} title="See this page's code"><Code2 className="h-3.5 w-3.5" /></Seg>}
      <Button size="sm" variant="outline" className="h-7 shrink-0 gap-1 text-xs" onClick={() => { setShowReadiness(true); void runCheck(); }} title="Check whether this page is ready to publish">
        <ClipboardCheck className="h-3.5 w-3.5" /><span className="hidden xl:inline">Ready to publish?</span><span className="xl:hidden">Check</span>
      </Button>
      {!preview.port && (
        <Button size="sm" className="h-7 shrink-0 text-xs" disabled={preview.isStarting} onClick={() => void preview.startPreview()}>
          {preview.isStarting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} Start the app
        </Button>
      )}
      <Seg active={rightOpen} onClick={() => setRightOpen(!rightOpen)} title="Show or hide settings (⌘.)"><PanelRight className="h-3.5 w-3.5" /></Seg>
    </div>
  );
}
