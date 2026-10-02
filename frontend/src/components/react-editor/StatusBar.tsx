"use client";
import { BREAKPOINTS } from "./lib/classes";
import { checkModel } from "./lib/readiness";
import { saveLabel, useEditorStore } from "./store";
import { cn } from "@/lib/utils";

export function StatusBar() {
  const doc = useEditorStore((s) => s.doc);
  const selection = useEditorStore((s) => s.selection);
  const mode = useEditorStore((s) => s.mode);
  const saveState = useEditorStore((s) => s.saveState);
  const saveError = useEditorStore((s) => s.saveError);
  const frameWidth = useEditorStore((s) => s.frameWidth);
  const serverFindings = useEditorStore((s) => s.serverFindings);
  const setShowReadiness = useEditorStore((s) => s.setShowReadiness);
  const viewLevel = useEditorStore((s) => s.viewLevel);
  const width = frameWidth();
  const bp = BREAKPOINTS.slice().reverse().find((b) => width >= b.minWidth);
  const own = doc ? checkModel(doc) : [];
  const mustFix = own.filter((f) => f.severity === "must-fix").length + serverFindings.length;
  const save = saveLabel(saveState, saveError);

  return (
    <div className="flex h-6 shrink-0 items-center gap-3 border-t border-border bg-card px-3 text-[11px] text-muted-foreground">
      <span className="truncate">{doc ? `${doc.page.name} · ${doc.page.route}` : "No page open"}</span>
      <span>{selection.length ? `${selection.length} selected` : "Nothing selected"}</span>
      <span>{width}px · {bp?.label ?? "All screens"}</span>
      <span className={cn("rounded px-1", mode === "preview" ? "bg-emerald-600/15 text-emerald-700" : "bg-primary/10 text-primary")}>{mode === "preview" ? "Preview" : "Design"}</span>
      <button type="button" className={cn("hover:underline", mustFix ? "text-destructive" : "")} onClick={() => setShowReadiness(true)}>
        {mustFix ? `${mustFix} to fix before publishing` : own.length ? `${own.length} suggestion${own.length === 1 ? "" : "s"}` : "No problems found"}
      </button>
      <div className="flex-1" />
      {viewLevel === "advanced" && doc && <span className="font-mono">rev {doc.revision.slice(0, 8)}</span>}
      <span className={cn(save.tone === "bad" && "text-destructive", save.tone === "ok" && "text-emerald-600")}>{save.text}</span>
    </div>
  );
}
