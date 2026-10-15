"use client";

/**
 * The drafts side by side: for each its pitch, roles, screen strip (drawn
 * in the company's brand when first opened), records, rules, what it
 * leaves out, what Forge cannot do yet, and a cost and time range — never a
 * quote. Versions with what changed; a note pinned on a screen or a line;
 * Revise and Build go through the conversation so Smith does them.
 */
import { useState } from "react";
import { Hammer, MessageSquarePlus, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NeedChip } from "./CardsPanel";
import { ScreenDrawing } from "./ScreenDrawing";
import type { Draft, Drawing } from "./types";

export function money(n: number): string { return `$${n.toFixed(2)}`; }

export function DraftsPanel({ drafts, drawings, drawingPath, onOpen, onDraw, onPin, onSend, onCompose, onOpenDrawing, built }:
  { drafts: Draft[]; drawings: Drawing[]; drawingPath: (id: string, kind: "html" | "png") => string;
    onOpen: (did: string) => void; onDraw: (did: string) => void; onPin: (did: string, on: string, text: string) => Promise<void>;
    onSend: (text: string) => void; onCompose: (text: string) => void; onOpenDrawing: (d: Drawing) => void; built: boolean }) {
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [pinning, setPinning] = useState<{ did: string; on: string } | null>(null);
  const [noteText, setNoteText] = useState("");
  if (drafts.length === 0) {
    return <p className="text-sm text-muted-foreground py-6 text-center">No drafts yet. Ask Smith for two or three once the cards are in.</p>;
  }
  const open = (did: string) => {
    if (opened.has(did)) return;
    setOpened(new Set([...opened, did]));
    onOpen(did);
  };
  const pin = async () => {
    if (!pinning || !noteText.trim()) return;
    await onPin(pinning.did, pinning.on, noteText.trim());
    setPinning(null); setNoteText("");
  };
  const cols = Math.min(drafts.length, 3);
  return (
    <div className="space-y-3 text-sm">
      <div className={`grid gap-3 ${cols === 1 ? "grid-cols-1" : cols === 2 ? "grid-cols-2" : "grid-cols-3"}`}>
        {drafts.map((d) => {
          const mine = drawings.filter((r) => r.scope === `draft:${d.id}`);
          const isOpen = opened.has(d.id);
          const est = d.estimate;
          return (
            <article key={d.id} className="rounded-lg border p-3 space-y-2 min-w-0" data-testid="draft">
              <header>
                <div className="flex items-center justify-between gap-2">
                  <h4 className="font-semibold truncate">{d.title}</h4>
                  <span className="text-[11px] text-muted-foreground shrink-0">v{d.version}</span>
                </div>
                <p className="text-xs">{d.pitch}</p>
              </header>
              <div className="text-xs rounded bg-muted/50 px-2 py-1" data-testid="estimate">
                About <b>{money(est.cost.low)}–{money(est.cost.high)}</b> and <b>{est.minutes.low}–{est.minutes.high} min</b> to build,
                fixes after ≈ {money(est.fixes.low)}–{money(est.fixes.high)} · {est.units} units
              </div>
              {d.cannot_yet.length > 0 && (
                <div className="flex flex-wrap gap-1" data-testid="cannot-yet">{d.cannot_yet.map((c) => <NeedChip key={c.kind} need={c.kind} status={c.status} />)}</div>
              )}
              <section>
                <div className="text-[11px] font-semibold uppercase text-muted-foreground">Screens ({d.screens.length})</div>
                {!isOpen ? (
                  <Button size="sm" variant="outline" className="h-7 text-xs mt-1" onClick={() => open(d.id)}>Open — draw its screens</Button>
                ) : (
                  <div className="flex gap-2 overflow-x-auto py-1">
                    {d.screens.map((s) => {
                      const r = mine.find((x) => x.screen === s.name);
                      return (
                        <div key={s.name} className="shrink-0 w-32 space-y-1" title={s.purpose}>
                          <div className="scale-[0.4] origin-top-left h-[150px] w-32 overflow-hidden">
                            <ScreenDrawing drawing={r} path={drawingPath} onOpen={onOpenDrawing} onRedraw={() => onDraw(d.id)} />
                          </div>
                          <div className="text-[11px] truncate">{s.name}</div>
                          <button type="button" className="text-[11px] text-muted-foreground inline-flex items-center gap-1 hover:text-foreground"
                            onClick={() => setPinning({ did: d.id, on: `screen:${s.name}` })}><MessageSquarePlus className="h-3 w-3" /> note</button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>
              <section className="text-xs space-y-1">
                <div><span className="font-semibold uppercase text-muted-foreground text-[11px]">Roles</span> {d.roles.map((r) => r.name).join(", ")}</div>
                <div><span className="font-semibold uppercase text-muted-foreground text-[11px]">Records</span> {d.records.map((r) => r.name).join(", ")}</div>
                {d.features.length > 0 && (
                  <div><span className="font-semibold uppercase text-muted-foreground text-[11px]">First version</span>{" "}
                    {d.features.filter((f) => (f.priority ?? "should") === "must").map((f) => f.name).join(", ")}</div>
                )}
                {d.rules && d.rules.length > 0 && (
                  <ul className="list-disc pl-4">{d.rules.map((r, i) => (
                    <li key={i} className="group">{r}
                      <button type="button" className="ml-1 opacity-0 group-hover:opacity-100 text-muted-foreground" onClick={() => setPinning({ did: d.id, on: `rule:${r}` })}>
                        <MessageSquarePlus className="h-3 w-3 inline" /></button>
                    </li>))}</ul>
                )}
                {d.left_out && d.left_out.length > 0 && <div><span className="font-semibold uppercase text-muted-foreground text-[11px]">Left out</span> {d.left_out.join("; ")}</div>}
                {d.assumed && d.assumed.length > 0 && <div><span className="font-semibold uppercase text-muted-foreground text-[11px]">Assumed</span> {d.assumed.join("; ")}</div>}
              </section>
              {d.notes.length > 0 && (
                <ul className="text-[11px] space-y-0.5 border-t pt-1">
                  {d.notes.map((n, i) => <li key={i}><span className="text-muted-foreground">{n.on}:</span> {n.text}</li>)}
                </ul>
              )}
              {d.versions && d.versions.length > 1 && (
                <div className="text-[11px] text-muted-foreground border-t pt-1">
                  {d.versions.map((v) => <div key={v.version} title={v.changed}>v{v.version} — {v.changed}</div>)}
                </div>
              )}
              {pinning?.did === d.id && (
                <div className="flex gap-1">
                  <input autoFocus value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder={`Note on ${pinning.on}`}
                    className="h-7 flex-1 rounded border bg-background px-2 text-xs" onKeyDown={(e) => { if (e.key === "Enter") void pin(); }} />
                  <Button size="sm" className="h-7 text-xs" onClick={() => void pin()}>Pin</Button>
                </div>
              )}
              <footer className="flex gap-2 pt-1">
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => onCompose(`Revise draft ${d.id} (“${d.title}”): `)}>
                  <Pencil className="h-3 w-3 mr-1" /> Revise
                </Button>
                {!built && (
                  <Button size="sm" className="h-7 text-xs" onClick={() => onSend(`Build draft ${d.id} (“${d.title}”)`)}>
                    <Hammer className="h-3 w-3 mr-1" /> Build this draft
                  </Button>
                )}
              </footer>
            </article>
          );
        })}
      </div>
    </div>
  );
}
