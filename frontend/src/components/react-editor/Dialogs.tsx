"use client";
/** Readiness check (UX-011), version history (UX-007) and the page's code (Advanced). */
import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, RotateCcw, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { groupFindings } from "./lib/readiness";
import { historyLabel, useEditorStore } from "./store";
import type { Finding } from "./types";

export function ReadinessDialog() {
  const open = useEditorStore((s) => s.showReadiness);
  const setOpen = useEditorStore((s) => s.setShowReadiness);
  const doc = useEditorStore((s) => s.doc);
  const serverFindings = useEditorStore((s) => s.serverFindings);
  const checkedRevision = useEditorStore((s) => s.checkedRevision);
  const checking = useEditorStore((s) => s.checking);
  const runCheck = useEditorStore((s) => s.runCheck);
  const select = useEditorStore((s) => s.select);
  const setLeftTab = useEditorStore((s) => s.setLeftTab);
  const setSmith = useEditorStore((s) => s.setSmith);
  const groups = useMemo(() => (doc ? groupFindings(doc, checkedRevision === doc.revision ? serverFindings : []) : null), [doc, serverFindings, checkedRevision]);
  const stale = doc && checkedRevision !== doc.revision;

  const goTo = (f: Finding) => {
    if (!f.nodeId) return;
    select([f.nodeId]);
    setLeftTab("layers");
    setOpen(false);
  };
  const askFix = (f: Finding) => {
    if (f.nodeId) select([f.nodeId]);
    setSmith({ open: true, expanded: true, prompt: `Fix this: ${f.plain}` });
    setOpen(false);
  };

  const Row = ({ f, tone }: { f: Finding; tone: "bad" | "warn" }) => (
    <li className="flex items-start gap-2 py-1.5 text-sm">
      {tone === "bad" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />}
      <span className="flex-1">{f.plain}{f.line && !f.nodeId ? <span className="text-muted-foreground"> (line {f.line})</span> : null}</span>
      {f.nodeId && <Button size="xs" variant="outline" onClick={() => goTo(f)}>Go to it</Button>}
      <Button size="xs" variant="ghost" onClick={() => askFix(f)}><Sparkles className="h-3 w-3" /> Ask Smith</Button>
    </li>
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Is this page ready to publish?</DialogTitle>
          <DialogDescription>
            {checking ? <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Checking the page against the app…</span>
              : stale ? <span>The compiler's check is from an earlier version. <button type="button" className="text-primary hover:underline" onClick={() => void runCheck()}>Check again</button></span>
              : "Checked just now. Publishing itself happens from the project's Publish button."}
          </DialogDescription>
        </DialogHeader>
        {groups && (
          <div className="max-h-[60vh] space-y-3 overflow-auto">
            <section>
              <h4 className={cn("text-xs font-semibold uppercase tracking-wide", groups.mustFix.length ? "text-destructive" : "text-muted-foreground")}>Must fix ({groups.mustFix.length})</h4>
              {groups.mustFix.length ? <ul className="divide-y divide-border">{groups.mustFix.map((f, i) => <Row key={i} f={f} tone="bad" />)}</ul> : <p className="py-1 text-sm text-muted-foreground">Nothing blocks this page.</p>}
            </section>
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-600">Recommended ({groups.recommended.length})</h4>
              {groups.recommended.length ? <ul className="divide-y divide-border">{groups.recommended.map((f, i) => <Row key={i} f={f} tone="warn" />)}</ul> : <p className="py-1 text-sm text-muted-foreground">No suggestions.</p>}
            </section>
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-emerald-600">Ready</h4>
              <ul>{groups.ready.map((r) => <li key={r} className="flex items-center gap-2 py-1 text-sm"><CheckCircle2 className="h-4 w-4 text-emerald-600" />{r}</li>)}</ul>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function HistoryDialog() {
  const open = useEditorStore((s) => s.showHistory);
  const setOpen = useEditorStore((s) => s.setShowHistory);
  const doc = useEditorStore((s) => s.doc);
  const restore = useEditorStore((s) => s.restore);
  const busy = useEditorStore((s) => s.busy);
  const entries = [...(doc?.history ?? [])].reverse();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Versions of this page</DialogTitle>
          <DialogDescription>Every saved change is kept. Restoring makes an older version the current one — you can undo that too.</DialogDescription>
        </DialogHeader>
        <ul className="max-h-[60vh] divide-y divide-border overflow-auto">
          {entries.map((h) => {
            const current = h.revision === doc?.revision;
            return (
              <li key={`${h.revision}-${h.at}`} className="flex items-center gap-2 py-2 text-sm">
                <span className={cn("h-2 w-2 shrink-0 rounded-full", current ? "bg-emerald-500" : h.kind === "smith" ? "bg-primary" : "bg-muted-foreground/40")} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{historyLabel(h)}{current ? " · current" : ""}</span>
                  <span className="block text-[11px] text-muted-foreground">{new Date(h.at).toLocaleString()}{h.kind === "smith" ? " · by Smith" : h.kind === "restore" ? " · restored" : ""}</span>
                </span>
                {!current && <Button size="xs" variant="outline" disabled={busy} onClick={() => void restore(h.revision)}><RotateCcw className="h-3 w-3" /> Restore</Button>}
              </li>
            );
          })}
          {!entries.length && <li className="py-2 text-sm text-muted-foreground">No versions yet.</li>}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

export function CodeDialog() {
  const open = useEditorStore((s) => s.showCode);
  const setOpen = useEditorStore((s) => s.setShowCode);
  const doc = useEditorStore((s) => s.doc);
  const selection = useEditorStore((s) => s.selection);
  const [which, setWhich] = useState<"view" | "load">("view");
  const node = selection[0] ? doc?.model?.nodes[selection[0]] : null;
  const src = doc?.source?.[which] ?? "";
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{doc?.page.file ?? "The page's code"}</DialogTitle>
          <DialogDescription>Read-only here. Every change made in the editor lands in this file; to change the code directly, ask Smith or edit it in the Code tab.</DialogDescription>
        </DialogHeader>
        <div className="flex gap-1">
          <Button size="xs" variant={which === "view" ? "default" : "outline"} onClick={() => setWhich("view")}>The screen (view.tsx)</Button>
          <Button size="xs" variant={which === "load" ? "default" : "outline"} onClick={() => setWhich("load")}>What it loads (load.ts)</Button>
        </div>
        <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3 font-mono text-[11px] leading-relaxed">
          {src.split("\n").map((line, i) => {
            const n = i + 1;
            const hit = which === "view" && node && n >= node.line && n <= node.endLine;
            return <div key={i} className={cn(hit && "bg-primary/10")}><span className="mr-3 inline-block w-8 select-none text-right text-muted-foreground">{n}</span>{line}</div>;
          })}
        </pre>
      </DialogContent>
    </Dialog>
  );
}
