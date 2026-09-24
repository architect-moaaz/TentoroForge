"use client";
/**
 * The build as a level map you can play with, inside the run panel.
 *
 * Each level is a row of the DAG: the steps on it run side by side. Open a
 * step to read what it makes and see each of its subjects — what landed, in
 * words — and open a subject to read what the reviewer said and, for a page,
 * to see the screenshot it was scored on. Pages appear in a gallery as they
 * are looked at. Points, a streak, a rank and badges are earned from the
 * run's own record; two bets placed before the pages are written resolve
 * when the build ends. Nothing here is guessed: see `questModel`.
 */
import { useEffect, useMemo, useState } from "react";
import { Award, CheckCircle2, ChevronDown, ChevronRight, Circle, Eye, Flame, Loader2, Sparkles, XCircle } from "lucide-react";

import type { BlueprintRun, RunLook } from "@/hooks/useBlueprintRun";
import { cn } from "@/lib/utils";

import { STAGE_MAKES } from "./stages";
import { questModel, type Cell, type CellState, type Level, type Outcomes, type QuestModel, type StepCard } from "./questModel";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

const CELL: Record<CellState, string> = {
  pending: "bg-muted",
  done: "bg-primary/40",
  review: "bg-primary/70 animate-pulse",
  sent_back: "bg-amber-500",
  retry: "bg-amber-400 ring-1 ring-amber-600",
  passed: "bg-green-500",
  noted: "bg-amber-300",
  waiting: "bg-sky-300 animate-pulse",
};

const CELL_WORD: Record<CellState, string> = {
  pending: "not started", done: "written", review: "under review", sent_back: "sent back",
  retry: "asked again", passed: "passed", noted: "noted for later", waiting: "waiting for the API",
};

/** The two bets a watcher can place before the pages are written. */
export const BETS = {
  allFirstLook: { question: "Will every page pass the reviewer's first look?", options: ["Yes", "No"] as const, bonus: 50 },
  mostSentBack: { question: "Which step will be sent back the most?",
                  options: ["entity_fields", "page_details", "workflow_steps", "page_code"] as const, bonus: 75 },
} as const;
export type Bets = { allFirstLook?: "Yes" | "No"; mostSentBack?: string };

/** The bonus a set of bets earned against what happened; 0 while the run is on. */
export function betBonus(bets: Bets, outcomes: Outcomes): number {
  let bonus = 0;
  if (outcomes.allFirstLook != null && bets.allFirstLook) {
    if ((bets.allFirstLook === "Yes") === outcomes.allFirstLook) bonus += BETS.allFirstLook.bonus;
  }
  if (outcomes.mostSentBack != null && bets.mostSentBack && bets.mostSentBack === outcomes.mostSentBack) {
    bonus += BETS.mostSentBack.bonus;
  }
  return bonus;
}

function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try { const raw = localStorage.getItem(key); if (raw) setValue(JSON.parse(raw) as T); } catch { /* no storage */ }
  }, [key]);
  const set = (v: T) => { setValue(v); try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* no storage */ } };
  return [value, set];
}

/** A look's screenshot, fetched the way every authenticated request is. */
function useLookImage(projectId: string | undefined, pageId: string, attempt: number, name: string, enabled: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled || !projectId) return;
    let live = true, made: string | null = null;
    (async () => {
      try {
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/looks/${pageId}/${attempt}/${name}`,
                                { headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: "include" });
        if (!res.ok || !live) return;
        made = URL.createObjectURL(await res.blob());
        setUrl(made);
      } catch { /* a missing picture never takes the panel down */ }
    })();
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [projectId, pageId, attempt, name, enabled]);
  return url;
}

function ScoreChip({ look }: { look: RunLook }) {
  const pass = look.verdict === "pass";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums",
                        pass ? "bg-green-500/15 text-green-700" : "bg-amber-500/15 text-amber-800")}>
      <Eye className="h-3 w-3" /> {look.score}/10{look.attempt > 1 ? ` · look ${look.attempt}` : ""}
    </span>
  );
}

function LookThumb({ projectId, pageId, look, onZoom }: { projectId?: string; pageId: string; look: RunLook; onZoom: (url: string) => void }) {
  const url = useLookImage(projectId, pageId, look.attempt, "desktop", look.shots.includes("desktop"));
  return (
    <button type="button" onClick={() => url && onZoom(url)} title={`${look.route}: ${look.score}/10`}
            className="group relative w-28 shrink-0 overflow-hidden rounded-md border bg-muted text-left">
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={look.route} className="h-16 w-full object-cover object-top transition group-hover:opacity-90" />
      ) : (
        <div className="grid h-16 w-full place-items-center text-[10px] text-muted-foreground">{look.route}</div>
      )}
      <div className="flex items-center justify-between gap-1 px-1 py-0.5">
        <span className="truncate font-mono text-[9px] text-muted-foreground">{look.route}</span>
        <ScoreChip look={look} />
      </div>
    </button>
  );
}

function StateIcon({ state }: { state: StepCard["state"] }) {
  if (state === "done") return <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />;
  if (state === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />;
  if (state === "failed") return <XCircle className="h-3.5 w-3.5 text-destructive" />;
  return <Circle className="h-3.5 w-3.5 text-muted-foreground/40" />;
}

type Pick = { node: string; subject: string } | null;

function Card({ step, open, onOpen, picked, onPick }: {
  step: StepCard; open: boolean; onOpen: () => void; picked: Pick; onPick: (p: Pick) => void;
}) {
  const fans = step.total > 1;
  return (
    <div className={cn("min-w-0 flex-1 rounded-md border p-2 text-xs",
                       step.state === "running" && "border-primary/60 bg-primary/5",
                       step.state === "done" && "bg-muted/40")}>
      <button type="button" onClick={onOpen} className="flex w-full items-center gap-1.5 text-left"
              aria-expanded={open} data-step={step.key}
              title={fans ? `${step.done} of ${step.total} · ${step.repairs} sent back · ${step.retries} asked again` : "What this step makes"}>
        <StateIcon state={step.state} />
        <span className={cn("truncate font-medium", step.state === "waiting" && "text-muted-foreground")}>{step.label}</span>
        {step.xp > 0 && <span className="ml-auto shrink-0 tabular-nums text-[10px] text-muted-foreground">+{step.xp}</span>}
        {step.cleanSweep && <Award className="h-3.5 w-3.5 shrink-0 text-amber-500" aria-label="Clean sweep" />}
      </button>
      {fans && (
        <div className="mt-1.5 flex flex-wrap gap-0.5" aria-label={`${step.done} of ${step.total} subjects`}>
          {step.cells.map((c) => (
            <button type="button" key={c.subject} data-cell={c.subject}
                    onClick={() => onPick(picked?.subject === c.subject && picked.node === step.key ? null : { node: step.key, subject: c.subject })}
                    title={`${c.subject}: ${CELL_WORD[c.state]}${c.summary ? ` — ${c.summary}` : ""}${c.note ? ` — ${c.note}` : ""}`}
                    className={cn("h-2.5 w-2.5 rounded-sm transition hover:scale-125", CELL[c.state],
                                  picked?.subject === c.subject && picked.node === step.key && "ring-2 ring-foreground ring-offset-1")} />
          ))}
        </div>
      )}
      {fans && (
        <div className="mt-1 text-[10px] tabular-nums text-muted-foreground">
          {step.done}/{step.total}
          {step.repairs > 0 && ` · ${step.repairs} back`}
          {step.retries > 0 && ` · ${step.retries} again`}
        </div>
      )}
      {open && (
        <div className="mt-2 border-t pt-2 text-[11px]">
          <p className="text-muted-foreground">{STAGE_MAKES[step.key] ?? "One step of the build."}</p>
          {fans && step.cells.some((c) => c.state !== "pending") && (
            <ul className="mt-1.5 max-h-40 space-y-0.5 overflow-y-auto">
              {step.cells.filter((c) => c.state !== "pending").map((c) => (
                <li key={c.subject}>
                  <button type="button" onClick={() => onPick({ node: step.key, subject: c.subject })}
                          className={cn("flex w-full items-start gap-1.5 rounded px-1 py-0.5 text-left hover:bg-muted",
                                        picked?.subject === c.subject && picked.node === step.key && "bg-muted")}>
                    <span className={cn("mt-1 h-2 w-2 shrink-0 rounded-sm", CELL[c.state])} />
                    <span className="min-w-0 flex-1 truncate">{c.summary ?? c.subject}</span>
                    {c.look && <ScoreChip look={c.look} />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Detail({ cell, node, projectId, onZoom, onClose }: { cell: Cell; node: string; projectId?: string; onZoom: (u: string) => void; onClose: () => void }) {
  const look = cell.look;
  return (
    <div data-testid="quest-detail" className="mt-2 rounded-md border bg-card p-2 text-[11px]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium">{cell.summary ?? cell.subject}</div>
          <div className="text-muted-foreground">{cell.subject} · {CELL_WORD[cell.state]}{cell.note ? ` — ${cell.note}` : ""}</div>
        </div>
        <button type="button" onClick={onClose} className="shrink-0 text-muted-foreground hover:text-foreground">×</button>
      </div>
      {look && (
        <div className="mt-2 flex gap-2">
          <LookThumb projectId={projectId} pageId={cell.subject} look={look} onZoom={onZoom} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5"><ScoreChip look={look} /><span className="text-muted-foreground">{look.verdict === "pass" ? "passed" : "sent back"}{look.broken ? ` · ${look.broken} broken` : ""}</span></div>
            {look.issues.length > 0 && (
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
                {look.issues.slice(0, 4).map((i, k) => <li key={k}>{i}</li>)}
              </ul>
            )}
          </div>
        </div>
      )}
      <div className="mt-1 text-[10px] text-muted-foreground">{node}</div>
    </div>
  );
}

function LevelRow({ level, open, onToggle, openStep, onOpenStep, picked, onPick }: {
  level: Level; open: boolean; onToggle: () => void;
  openStep: string | null; onOpenStep: (k: string | null) => void; picked: Pick; onPick: (p: Pick) => void;
}) {
  const Chevron = open ? ChevronDown : ChevronRight;
  const xp = level.steps.reduce((a, s) => a + s.xp, 0);
  return (
    <li className={cn("rounded-md", level.state === "ahead" && "opacity-50")}>
      <button type="button" onClick={onToggle}
              className="flex w-full items-center gap-1.5 py-0.5 text-left text-[11px] text-muted-foreground hover:text-foreground">
        <Chevron className="h-3 w-3 shrink-0" />
        <span className="font-medium tabular-nums">Level {level.index}</span>
        <span className="truncate">{level.steps.map((s) => s.label).join(" · ")}</span>
        {xp > 0 && <span className="ml-auto shrink-0 tabular-nums text-[10px]">+{xp}</span>}
        {level.state === "done" && <CheckCircle2 className={cn("h-3 w-3 shrink-0 text-green-600", xp === 0 && "ml-auto")} />}
        {level.state === "active" && <Loader2 className={cn("h-3 w-3 shrink-0 animate-spin text-primary", xp === 0 && "ml-auto")} />}
      </button>
      {open && (
        <div className={cn("mb-1 ml-4 gap-1.5", level.steps.length > 2 ? "grid grid-cols-2" : "flex")}>
          {level.steps.map((s) => (
            <Card key={s.key} step={s} open={openStep === s.key} onOpen={() => onOpenStep(openStep === s.key ? null : s.key)}
                  picked={picked} onPick={onPick} />
          ))}
        </div>
      )}
    </li>
  );
}

function BetsCard({ bets, setBets, outcomes, locked }: { bets: Bets; setBets: (b: Bets) => void; outcomes: Outcomes; locked: boolean }) {
  const resolved = outcomes.allFirstLook != null;
  const label = (k: string) => ({ entity_fields: "Entity fields", page_details: "Page contracts", workflow_steps: "Workflow steps", page_code: "React pages" } as Record<string, string>)[k] ?? k;
  return (
    <div data-testid="quest-bets" className="mt-2 rounded-md border border-dashed p-2 text-[11px]">
      <div className="mb-1 flex items-center gap-1 font-medium"><Sparkles className="h-3 w-3 text-amber-500" /> {resolved ? "Your bets" : locked ? "Bets are locked" : "Place your bets"}</div>
      {(Object.keys(BETS) as (keyof typeof BETS)[]).map((k) => {
        const q = BETS[k];
        const mine = bets[k];
        const truth = k === "allFirstLook" ? (outcomes.allFirstLook == null ? null : outcomes.allFirstLook ? "Yes" : "No") : outcomes.mostSentBack;
        return (
          <div key={k} className="mb-1">
            <div className="text-muted-foreground">{q.question} <span className="tabular-nums">(+{q.bonus})</span></div>
            <div className="mt-0.5 flex flex-wrap gap-1">
              {q.options.map((o) => {
                const chosen = mine === o;
                const right = truth != null && o === truth;
                return (
                  <button type="button" key={o} disabled={locked || resolved} onClick={() => setBets({ ...bets, [k]: o })}
                          className={cn("rounded-full border px-2 py-0.5 transition",
                                        chosen && "border-primary bg-primary/10 font-medium",
                                        right && "border-green-600 bg-green-500/10",
                                        resolved && chosen && !right && "line-through opacity-60",
                                        (locked || resolved) && "cursor-default")}>
                    {label(o)}
                  </button>
                );
              })}
              {truth != null && mine && <span className="self-center text-muted-foreground">{mine === truth ? "you called it" : `it was ${label(truth)}`}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function QuestMap({ run, projectId }: { run: BlueprintRun; projectId?: string }) {
  const model: QuestModel = useMemo(() => questModel(run), [run]);
  const [pinned, setPinned] = useState<Record<number, boolean>>({});
  const [openStep, setOpenStep] = useState<string | null>(null);
  const [picked, setPicked] = useState<Pick>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const [bets, setBets] = useStored<Bets>(`forge:bets:${projectId ?? "run"}`, {});
  const isOpen = (l: Level) => pinned[l.index] ?? l.state === "active";
  const pickedCell = picked
    ? model.levels.flatMap((l) => l.steps).find((s) => s.key === picked.node)?.cells.find((c) => c.subject === picked.subject) ?? null
    : null;
  const pagesStarted = run.nodes.some((n) => n.key === "page_code" && n.state !== "waiting");
  const bonus = betBonus(bets, model.outcomes);
  const xp = model.stats.xp + bonus;
  const complete = run.status === "complete";
  const toNext = model.rank.next ? Math.min(1, (xp - model.rank.at) / (model.rank.next - model.rank.at)) : 1;

  // A point earned is a point noticed: the score pulses when it changes.
  const [pulse, setPulse] = useState(false);
  useEffect(() => { setPulse(true); const t = setTimeout(() => setPulse(false), 600); return () => clearTimeout(t); }, [xp]);

  return (
    <div data-testid="quest-map">
      {model.levels.length > 0 && (
        <div className="mb-2 rounded-md border bg-gradient-to-r from-primary/10 to-transparent p-2">
          <div className="flex items-baseline justify-between text-xs">
            <span className="font-medium">
              {complete ? "Build report" : model.current ? `Level ${model.current} of ${model.levels.length}` : `${model.levels.length} levels`}
              {model.cleared > 0 && model.cleared < model.levels.length && (
                <span className="font-normal text-muted-foreground"> · {model.cleared} cleared</span>
              )}
            </span>
            <span className={cn("tabular-nums font-semibold transition", pulse && "scale-110 text-primary")} data-testid="quest-xp">
              {xp} XP
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
            <span className="font-medium text-foreground">{model.rank.name}</span>
            <div className="h-1 flex-1 overflow-hidden rounded bg-muted" title={model.rank.next ? `${model.rank.next - xp} to the next rank` : "top rank"}>
              <div className="h-full bg-primary transition-all duration-500" style={{ width: `${Math.round(toNext * 100)}%` }} />
            </div>
            {model.stats.streak >= 3 && (
              <span className="inline-flex items-center gap-0.5 text-amber-600" title={`${model.stats.streak} in a row without a send-back`}>
                <Flame className="h-3 w-3" /> {model.stats.streak}
              </span>
            )}
          </div>
          <div className="mt-1 text-[10px] tabular-nums text-muted-foreground">
            {model.stats.inFlight > 0 && `${model.stats.inFlight} running · `}
            {model.stats.calls} calls
            {model.stats.repairs > 0 && ` · ${model.stats.repairs} back`}
            {model.stats.retries > 0 && ` · ${model.stats.retries} again`}
            {model.stats.passRate != null && ` · ${Math.round(model.stats.passRate * 100)}% pass`}
            {model.stats.looks.total > 0 && ` · ${model.stats.looks.passed}/${model.stats.looks.total} pages passed the look`}
            {bonus > 0 && ` · +${bonus} from your bets`}
          </div>
        </div>
      )}
      {model.badges.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {model.badges.map((b) => (
            <span key={b.id} title={b.detail}
                  className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
              <Award className="h-3 w-3" /> {b.label}
            </span>
          ))}
        </div>
      )}
      <ul className="space-y-0.5">
        {model.levels.map((l) => (
          <LevelRow key={l.index} level={l} open={isOpen(l)}
                    onToggle={() => setPinned((p) => ({ ...p, [l.index]: !isOpen(l) }))}
                    openStep={openStep} onOpenStep={setOpenStep} picked={picked} onPick={setPicked} />
        ))}
      </ul>
      {pickedCell && picked && (
        <Detail cell={pickedCell} node={picked.node} projectId={projectId} onZoom={setZoom} onClose={() => setPicked(null)} />
      )}
      {model.paused && (
        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
          Paused — {model.paused}. Nothing is lost; the next build continues from here.
        </p>
      )}
      {model.looks.length > 0 && (
        <div className="mt-2 border-t pt-2">
          <div className="mb-1 flex items-center gap-1 text-[11px] font-medium"><Eye className="h-3 w-3" /> Pages, as the reviewer saw them</div>
          <div className="flex gap-1.5 overflow-x-auto pb-1" data-testid="quest-gallery">
            {model.looks.map((l) => {
              const cell = model.levels.flatMap((x) => x.steps).find((s) => s.key === "page_code")?.cells.find((c) => c.look === l);
              return <LookThumb key={`${l.route}:${l.attempt}`} projectId={projectId} pageId={cell?.subject ?? l.route} look={l} onZoom={setZoom} />;
            })}
          </div>
        </div>
      )}
      {model.landed.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t pt-2 text-[11px]" aria-label="Taking shape" data-testid="quest-landed">
          {model.landed.map((t) => (
            <li key={t.seq} className="flex gap-1.5">
              <span className="shrink-0 text-muted-foreground">{t.label}</span>
              <span className="truncate">{t.summary}</span>
            </li>
          ))}
        </ul>
      )}
      {model.ticker.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t pt-2 text-[11px]" aria-label="What the reviewer said">
          {model.ticker.map((t) => (
            <li key={t.seq} className={cn("flex gap-1.5",
                 t.tone === "pass" && "text-green-700", t.tone === "back" && "text-amber-700",
                 t.tone === "retry" && "text-amber-700", t.tone === "wait" && "text-sky-700",
                 t.tone === "look" && "text-foreground", t.tone === "note" && "text-muted-foreground")}>
              <span aria-hidden>{t.tone === "pass" ? "✓" : t.tone === "back" ? "↩" : t.tone === "retry" ? "⟳" : t.tone === "wait" ? "…" : t.tone === "look" ? "👁" : "•"}</span>
              <span className="truncate">{t.text}</span>
            </li>
          ))}
        </ul>
      )}
      {(run.status === "running" || (complete && (bets.allFirstLook || bets.mostSentBack))) && model.levels.length > 0 && (
        <BetsCard bets={bets} setBets={setBets} outcomes={model.outcomes} locked={pagesStarted && !complete} />
      )}
      {zoom && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-6" onClick={() => setZoom(null)} role="dialog" aria-modal="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={zoom} alt="page" className="max-h-full max-w-full rounded-lg shadow-2xl" />
        </div>
      )}
    </div>
  );
}
