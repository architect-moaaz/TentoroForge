"use client";
/**
 * Smith beside the selection (SMITH-001): the target, a prompt, an optional
 * note, and — after asking — a staged proposal to apply or discard
 * (SMITH-005). A proposal is made for one selection and one revision; it is
 * never applied to another (SMITH-006).
 */
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, ChevronUp, Loader2, Maximize2, Minimize2, Pin, PinOff, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { plainName } from "./lib/plain";
import { useEditorStore } from "./store";

const WIDTH = 340;

export function SmithWindow() {
  const doc = useEditorStore((s) => s.doc);
  const selection = useEditorStore((s) => s.selection);
  const rects = useEditorStore((s) => s.rects);
  const smith = useEditorStore((s) => s.smith);
  const setSmith = useEditorStore((s) => s.setSmith);
  const askSmith = useEditorStore((s) => s.askSmith);
  const cancelSmith = useEditorStore((s) => s.cancelSmith);
  const applyProposal = useEditorStore((s) => s.applyProposal);
  const discardProposal = useEditorStore((s) => s.discardProposal);
  const busy = useEditorStore((s) => s.busy);
  const viewLevel = useEditorStore((s) => s.viewLevel);
  const [prompt, setPrompt] = useState(smith.prompt);
  const [note, setNote] = useState(smith.annotation);
  const [showNote, setShowNote] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setPrompt(smith.prompt); }, [smith.prompt]);
  useEffect(() => { if (smith.open && smith.expanded) inputRef.current?.focus(); }, [smith.open, smith.expanded]);
  // A new selection gets a fresh window unless it is pinned in place.
  useEffect(() => { if (!smith.pinned) setPos(null); }, [selection, smith.pinned]);

  if (!doc?.model || !selection.length || !smith.open) return null;
  const nodes = selection.map((id) => doc.model!.nodes[id]).filter(Boolean);
  if (!nodes.length) return null;
  const target = nodes.length === 1 ? plainName(nodes[0], doc.registry) : `${nodes.length} things`;
  const proposal = smith.proposal;
  const stale = proposal ? proposal.baseRevision !== doc.revision : false;
  const forThis = proposal ? smith.proposalFor.join("|") === selection.join("|") : true;

  // Beside the selection, inside the canvas, away from the right edge.
  const rect = rects[selection[0]];
  const parent = ref.current?.parentElement;
  const pw = parent?.clientWidth ?? 800;
  const ph = parent?.clientHeight ?? 600;
  const width = Math.min(smith.expanded ? 448 : WIDTH, Math.max(240, pw - 16));
  const auto = rect
    ? { top: Math.max(44, Math.min(ph - 220, rect.top + 40)), left: Math.max(8, Math.min(pw - width - 8, rect.left + rect.width + 12)) }
    : { top: 48, left: Math.max(8, pw - width - 16) };
  const at = pos ?? auto;

  const ask = () => { if (prompt.trim()) void askSmith(prompt, note); };

  return (
    <div ref={ref} role="dialog" aria-label={`Smith, about ${target}`}
      className="absolute z-30 rounded-xl border border-border bg-card shadow-xl"
      style={{ top: at.top, left: at.left, width }}>
      <div className="flex cursor-move items-center gap-1 rounded-t-xl border-b border-border bg-muted/60 px-2 py-1.5"
        onMouseDown={(e) => { setDrag({ x: e.clientX - at.left, y: e.clientY - at.top }); }}
        onMouseMove={(e) => { if (drag) setPos({ top: e.clientY - drag.y, left: e.clientX - drag.x }); }}
        onMouseUp={() => setDrag(null)} onMouseLeave={() => setDrag(null)}>
        <Sparkles className="h-3.5 w-3.5 text-primary" />
        <span className="min-w-0 flex-1 truncate text-xs font-medium">Smith · {target}</span>
        <button type="button" className="rounded p-1 text-muted-foreground hover:bg-background" onClick={() => setSmith({ pinned: !smith.pinned })} title={smith.pinned ? "Unpin" : "Pin here"}>{smith.pinned ? <PinOff className="h-3 w-3" /> : <Pin className="h-3 w-3" />}</button>
        <button type="button" className="rounded p-1 text-muted-foreground hover:bg-background" onClick={() => setSmith({ expanded: !smith.expanded })} title={smith.expanded ? "Smaller" : "Larger"}>{smith.expanded ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}</button>
        <button type="button" className="rounded p-1 text-muted-foreground hover:bg-background" onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Expand" : "Collapse"}>{collapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}</button>
        <button type="button" className="rounded p-1 text-muted-foreground hover:bg-background" onClick={() => setSmith({ open: false })} title="Close (keeps the selection)"><X className="h-3 w-3" /></button>
      </div>
      {!collapsed && (
        <div className="p-2">
          <div className="flex gap-1">
            <Input ref={inputRef} className="h-8 text-xs" placeholder={nodes.length > 1 ? "e.g. put these side by side" : "e.g. make this bigger, or save this information"}
              value={prompt} onChange={(e) => setPrompt(e.target.value)} disabled={smith.busy}
              onKeyDown={(e) => { if (e.key === "Enter") ask(); }} aria-label="What should Smith change?" />
            {smith.busy ? (
              <Button size="sm" variant="outline" className="h-8 text-xs" onClick={cancelSmith}><Loader2 className="h-3 w-3 animate-spin" /> Stop</Button>
            ) : (
              <Button size="sm" className="h-8 text-xs" disabled={!prompt.trim()} onClick={ask}>Ask</Button>
            )}
          </div>
          <button type="button" className="mt-1 text-[11px] text-muted-foreground hover:underline" onClick={() => setShowNote(!showNote)}>{showNote ? "Hide note" : note ? "Edit note" : "Add a note about the selection"}</button>
          {showNote && <textarea className="mt-1 min-h-[2.5rem] w-full rounded-md border border-input bg-background p-1.5 text-xs" placeholder="e.g. only this button, not the others" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note about the selection" />}

          {smith.busy && <p className="mt-2 text-[11px] text-muted-foreground"><Loader2 className="mr-1 inline h-3 w-3 animate-spin" />Smith is working on “{smith.prompt}”… you can keep editing; the answer will be checked against the page as it is then.</p>}
          {smith.error && <p className="mt-2 rounded-md bg-destructive/10 p-2 text-[11px] text-destructive">{smith.error}</p>}

          {proposal && forThis && !smith.busy && (
            <div className="mt-2 rounded-lg border border-border bg-background p-2">
              {proposal.status === "needs-choice" ? (
                <>
                  <p className="text-xs font-medium">{proposal.questions[0]?.question}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {proposal.questions[0]?.options.map((o) => (
                      <Button key={o} size="sm" variant="outline" className="h-7 text-xs" onClick={() => void askSmith(proposal.prompt, proposal.annotation, { question: proposal.questions[0].question, choice: o })}>{o}</Button>
                    ))}
                  </div>
                </>
              ) : proposal.status === "applied" ? (
                <p className="flex items-center gap-1 text-xs text-emerald-700"><Check className="h-3 w-3" /> Applied — {proposal.summary} <button type="button" className="ml-1 text-primary hover:underline" onClick={() => void useEditorStore.getState().undo()}>Undo</button></p>
              ) : (
                <>
                  <p className="text-xs font-medium">{proposal.summary || (proposal.status === "nothing" ? "Smith did not find anything to change." : "Smith could not do this here.")}</p>
                  {proposal.explanation && <p className="mt-0.5 text-[11px] text-muted-foreground">{proposal.explanation}</p>}
                  {proposal.replacements.length > 0 && (
                    <p className="mt-1 text-[11px] text-muted-foreground">Changes {proposal.replacements.map((r) => plainName(doc.model!.nodes[r.nodeId] ?? { ...nodes[0], type: r.type }, doc.registry)).join(", ")}.
                      {proposal.expandsScope.length > 0 && <span className="text-amber-700"> Also changes the part around what you selected.</span>}</p>
                  )}
                  {proposal.needs.length > 0 && (
                    <div className="mt-1 rounded bg-amber-50 p-1.5 text-[11px] text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                      Needs more than this selection: <ul className="ml-3 list-disc">{proposal.needs.map((n, i) => <li key={i}>{n}</li>)}</ul>
                    </div>
                  )}
                  {proposal.refused.length > 0 && <p className="mt-1 text-[11px] text-muted-foreground">Left out: {proposal.refused.length} change{proposal.refused.length === 1 ? "" : "s"} outside the selection.</p>}
                  {!proposal.valid && proposal.findings.length > 0 && (
                    <div className="mt-1 rounded bg-destructive/10 p-1.5 text-[11px] text-destructive">
                      This would break the page, so it cannot be applied:
                      <ul className="ml-3 list-disc">{proposal.findings.slice(0, 3).map((f, i) => <li key={i}>{f.plain}</li>)}</ul>
                    </div>
                  )}
                  {stale && <p className="mt-1 text-[11px] text-amber-700">The page changed since this was proposed. Ask again to get a fresh proposal.</p>}
                  {viewLevel === "advanced" && proposal.replacements.length > 0 && (
                    <details className="mt-1 text-[11px]">
                      <summary className="cursor-pointer text-muted-foreground">Before / after (code)</summary>
                      {proposal.replacements.map((r) => (
                        <div key={r.nodeId} className="mt-1 grid grid-cols-2 gap-1">
                          <pre className="max-h-40 overflow-auto rounded bg-muted p-1 font-mono text-[10px]">{r.before}</pre>
                          <pre className="max-h-40 overflow-auto rounded bg-emerald-50 p-1 font-mono text-[10px] dark:bg-emerald-950/30">{r.after}</pre>
                        </div>
                      ))}
                    </details>
                  )}
                  <div className="mt-2 flex gap-1">
                    <Button size="sm" className="h-7 text-xs" disabled={!proposal.valid || stale || busy || !["ready"].includes(proposal.status)}
                      onClick={() => void applyProposal(proposal.expandsScope.length > 0)}>
                      {proposal.expandsScope.length > 0 ? "Apply, including the surrounding part" : "Apply"}
                    </Button>
                    <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => void discardProposal()}>Discard</Button>
                    {stale && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={ask}>Ask again</Button>}
                  </div>
                  <p className="mt-1 text-[10px] text-muted-foreground">Took {(proposal.timing.generationMs / 1000).toFixed(1)}s to write, {(proposal.timing.validationMs / 1000).toFixed(1)}s to check.</p>
                </>
              )}
            </div>
          )}
          {proposal && !forThis && <p className="mt-2 text-[11px] text-muted-foreground">Smith's last proposal was for a different selection — it will not be applied here.</p>}
        </div>
      )}
    </div>
  );
}
