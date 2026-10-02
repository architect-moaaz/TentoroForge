"use client";
/**
 * The application taking shape, inside the run panel.
 *
 * Above: the product's areas — data, screens, workflows, design, build — each
 * a ring and a count in the product's own terms ("12 of 27 pages written"),
 * the milestones reached, how the reviews are going, and the pages as the
 * reviewer saw them. Below, the build itself as a level map: each level a row
 * of the DAG, the steps on it running side by side. Open a step to read what
 * it makes and see each of its subjects — what landed, in words — and open a
 * subject to read what the reviewer said and, for a page, to see the
 * screenshot it was scored on. Nothing here is guessed: see `questModel`.
 */
import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, Circle, Eye, Loader2, XCircle } from "lucide-react";

import type { BlueprintRun, RunLook } from "@/hooks/useBlueprintRun";
import { cn } from "@/lib/utils";

import { STAGE_MAKES } from "./stages";
import { questModel, type Area, type Cell, type CellState, type Level, type Milestone, type QuestModel, type StepCard } from "./questModel";

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
        {step.cleanSweep && <CheckCircle2 className="ml-auto h-3.5 w-3.5 shrink-0 text-green-600" aria-label="All passed first review" />}
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
  return (
    <li className={cn("rounded-md", level.state === "ahead" && "opacity-50")}>
      <button type="button" onClick={onToggle}
              className="flex w-full items-center gap-1.5 py-0.5 text-left text-[11px] text-muted-foreground hover:text-foreground">
        <Chevron className="h-3 w-3 shrink-0" />
        <span className="font-medium tabular-nums">Level {level.index}</span>
        <span className="truncate">{level.steps.map((s) => s.label).join(" · ")}</span>
        {level.state === "done" && <CheckCircle2 className="ml-auto h-3 w-3 shrink-0 text-green-600" />}
        {level.state === "active" && <Loader2 className="ml-auto h-3 w-3 shrink-0 animate-spin text-primary" />}
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

/** A ring of progress, drawn in the app's own primary. */
function Ring({ value, size = 34 }: { value: number; size?: number }) {
  const r = (size - 4) / 2, c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={3} className="stroke-muted" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={3} strokeLinecap="round"
              className="stroke-primary transition-[stroke-dashoffset] duration-700"
              strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0, Math.min(1, value)))}
              transform={`rotate(-90 ${size / 2} ${size / 2})`} />
    </svg>
  );
}

function AreaTile({ area, open, onToggle }: { area: Area; open: boolean; onToggle: () => void }) {
  return (
    <div data-area={area.key} className={cn("rounded-md border p-2", area.state === "ahead" && "opacity-60", area.state === "done" && "bg-muted/40")}>
      <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full items-center gap-2 text-left">
        <Ring value={area.progress} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="font-medium">{area.label}</span>
            <span className="tabular-nums text-muted-foreground">{Math.round(area.progress * 100)}%</span>
          </div>
          <div className="truncate text-[10px] text-muted-foreground">{area.note || (area.state === "ahead" ? "not started" : "in progress")}</div>
        </div>
      </button>
      {open && (
        <ul className="mt-1.5 space-y-0.5 border-t pt-1.5 text-[10px]">
          {area.items.map((i) => (
            <li key={i.key} className="flex items-center gap-1.5">
              <StateIcon state={i.state} />
              <span className="min-w-0 flex-1 truncate">{i.label}</span>
              {i.total > 1 && <span className="tabular-nums text-muted-foreground">{i.done}/{i.total}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Milestones({ items }: { items: Milestone[] }) {
  if (!items.length) return null;
  return (
    <ol data-testid="quest-milestones" className="mt-2 flex flex-wrap items-center gap-y-1 text-[10px]">
      {items.map((m, i) => (
        <li key={m.key} className="flex shrink-0 items-center">
          <span className={cn("inline-flex items-center gap-1 whitespace-nowrap",
                              m.state === "done" ? "text-foreground" : m.state === "active" ? "font-medium text-primary" : "text-muted-foreground/70")}>
            {m.state === "done" ? <CheckCircle2 className="h-3 w-3 text-green-600" />
              : m.state === "active" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Circle className="h-3 w-3" />}
            {m.label}
          </span>
          {i < items.length - 1 && <span className={cn("mx-1.5 h-px w-4", m.state === "done" ? "bg-green-600/60" : "bg-border")} />}
        </li>
      ))}
    </ol>
  );
}

export function QuestMap({ run, projectId }: { run: BlueprintRun; projectId?: string }) {
  const model: QuestModel = useMemo(() => questModel(run), [run]);
  const [pinned, setPinned] = useState<Record<number, boolean>>({});
  const [openStep, setOpenStep] = useState<string | null>(null);
  const [picked, setPicked] = useState<Pick>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const [openArea, setOpenArea] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const isOpen = (l: Level) => pinned[l.index] ?? l.state === "active";
  const pickedCell = picked
    ? model.levels.flatMap((l) => l.steps).find((s) => s.key === picked.node)?.cells.find((c) => c.subject === picked.subject) ?? null
    : null;
  const complete = run.status === "complete";
  const review = model.stats.review;
  // The build detail opens itself when something needs a look — a send-back,
  // a retry, a wait — and stays where the person put it otherwise.
  const attention = model.stats.repairs + model.stats.retries > 0 || model.paused != null;
  useEffect(() => { if (attention) setDetailOpen(true); }, [attention]);

  return (
    <div data-testid="quest-map">
      {model.areas.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-1.5" data-testid="quest-areas">
            {model.areas.map((a) => (
              <AreaTile key={a.key} area={a} open={openArea === a.key} onToggle={() => setOpenArea(openArea === a.key ? null : a.key)} />
            ))}
          </div>
          <Milestones items={model.milestones} />
          {(review.passed > 0 || review.open > 0 || model.stats.looks.total > 0) && (
            <p data-testid="quest-review" className="mt-2 text-[11px] text-muted-foreground">
              <span className="font-medium text-foreground">Review</span>
              {` · ${review.passed} passed`}
              {review.fixed > 0 && ` · ${review.fixed} fixed after a send-back`}
              {review.open > 0 ? ` · ${review.open} open` : " · none open"}
              {model.stats.looks.total > 0 && ` · ${model.stats.looks.passed} of ${model.stats.looks.total} page reviews passed`}
            </p>
          )}
          {model.highlights.length > 0 && (
            <ul className="mt-1.5 flex flex-wrap gap-1" data-testid="quest-highlights">
              {model.highlights.map((h) => (
                <li key={h.id} title={h.detail}
                    className="inline-flex items-center gap-1 rounded-full border bg-card px-1.5 py-0.5 text-[10px] text-foreground">
                  <CheckCircle2 className="h-3 w-3 text-green-600" /> {h.label}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {model.looks.length > 0 && (
        <div className="mt-2 border-t pt-2">
          <div className="mb-1 flex items-center gap-1 text-[11px] font-medium"><Eye className="h-3 w-3" /> Pages, as reviewed</div>
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
      {model.levels.length > 0 && (
        <button type="button" onClick={() => setDetailOpen((v) => !v)} aria-expanded={detailOpen} data-testid="quest-detail-toggle"
                className="mt-2 flex w-full items-center gap-1.5 border-t pt-2 text-left text-[11px] text-muted-foreground hover:text-foreground">
          {detailOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <span className="font-medium">Build detail</span>
          <span className="tabular-nums">
            {complete ? `${model.levels.length} levels` : model.current ? `level ${model.current} of ${model.levels.length}` : `${model.levels.length} levels`}
            {model.stats.inFlight > 0 && ` · ${model.stats.inFlight} running`}
            {` · ${model.stats.calls} calls`}
            {model.stats.repairs > 0 && ` · ${model.stats.repairs} sent back`}
            {model.stats.retries > 0 && ` · ${model.stats.retries} retried`}
          </span>
        </button>
      )}
      <ul className={cn("mt-1 space-y-0.5", !detailOpen && "hidden")}>
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
      {model.ticker.length > 0 && detailOpen && (
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
      {zoom && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-6" onClick={() => setZoom(null)} role="dialog" aria-modal="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={zoom} alt="page" className="max-h-full max-w-full rounded-lg shadow-2xl" />
        </div>
      )}
    </div>
  );
}
