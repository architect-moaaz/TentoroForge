"use client";
/**
 * The build as a level map, inside the run panel.
 *
 * Each level is a row of the DAG: the steps on it run side by side. The
 * level in play is open, with a card per step; a step that fans out shows a
 * cell per subject, coloured by how it is faring — landed, under review,
 * sent back, asked again, passed, or waiting on the API. Done levels fold to
 * a line; levels ahead are dim. Below: what the reviewer just said, the
 * count of calls, repairs and retries, and the badges a clean run earns.
 */
import { useState } from "react";
import { Award, CheckCircle2, ChevronDown, ChevronRight, Circle, Loader2, XCircle } from "lucide-react";

import type { BlueprintRun } from "@/hooks/useBlueprintRun";
import { cn } from "@/lib/utils";

import { questModel, type CellState, type Level, type StepCard } from "./questModel";

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

function StateIcon({ state }: { state: StepCard["state"] }) {
  if (state === "done") return <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />;
  if (state === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />;
  if (state === "failed") return <XCircle className="h-3.5 w-3.5 text-destructive" />;
  return <Circle className="h-3.5 w-3.5 text-muted-foreground/40" />;
}

function Card({ step }: { step: StepCard }) {
  const fans = step.total > 1;
  return (
    <div className={cn("min-w-0 flex-1 rounded-md border p-2 text-xs",
                       step.state === "running" && "border-primary/60 bg-primary/5",
                       step.state === "done" && "bg-muted/40")}
         title={fans ? `${step.done} of ${step.total} · ${step.repairs} sent back · ${step.retries} asked again` : undefined}>
      <div className="flex items-center gap-1.5">
        <StateIcon state={step.state} />
        <span className={cn("truncate font-medium", step.state === "waiting" && "text-muted-foreground")}>{step.label}</span>
        {step.cleanSweep && <Award className="ml-auto h-3.5 w-3.5 shrink-0 text-amber-500" aria-label="Clean sweep" />}
      </div>
      {fans && (
        <div className="mt-1.5 flex flex-wrap gap-0.5" aria-label={`${step.done} of ${step.total} subjects`}>
          {step.cells.map((c) => (
            <span key={c.subject} title={`${c.subject}: ${CELL_WORD[c.state]}${c.note ? ` — ${c.note}` : ""}`}
                  className={cn("h-2 w-2 rounded-sm", CELL[c.state])} />
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
    </div>
  );
}

function LevelRow({ level, open, onToggle }: { level: Level; open: boolean; onToggle: () => void }) {
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <li className={cn("rounded-md", level.state === "ahead" && "opacity-50")}>
      <button type="button" onClick={onToggle}
              className="flex w-full items-center gap-1.5 py-0.5 text-left text-[11px] text-muted-foreground hover:text-foreground">
        <Chevron className="h-3 w-3 shrink-0" />
        <span className="font-medium tabular-nums">Level {level.index}</span>
        <span className="truncate">
          {level.steps.map((s) => s.label).join(" · ")}
        </span>
        {level.state === "done" && <CheckCircle2 className="ml-auto h-3 w-3 shrink-0 text-green-600" />}
        {level.state === "active" && <Loader2 className="ml-auto h-3 w-3 shrink-0 animate-spin text-primary" />}
      </button>
      {open && (
        <div className={cn("mb-1 ml-4 gap-1.5", level.steps.length > 2 ? "grid grid-cols-2" : "flex")}>
          {level.steps.map((s) => <Card key={s.key} step={s} />)}
        </div>
      )}
    </li>
  );
}

export function QuestMap({ run }: { run: BlueprintRun }) {
  const model = questModel(run);
  const [pinned, setPinned] = useState<Record<number, boolean>>({});
  const isOpen = (l: Level) => pinned[l.index] ?? l.state === "active";

  return (
    <div data-testid="quest-map">
      {model.levels.length > 0 && (
        <div className="mb-1 flex items-baseline justify-between text-xs">
          <span className="font-medium">
            {model.current ? `Level ${model.current} of ${model.levels.length}` : `${model.levels.length} levels`}
            {model.cleared > 0 && model.cleared < model.levels.length && (
              <span className="font-normal text-muted-foreground"> · {model.cleared} cleared</span>
            )}
          </span>
          <span className="tabular-nums text-muted-foreground">
            {model.stats.inFlight > 0 && `${model.stats.inFlight} running · `}
            {model.stats.calls} calls
            {model.stats.repairs > 0 && ` · ${model.stats.repairs} back`}
            {model.stats.retries > 0 && ` · ${model.stats.retries} again`}
            {model.stats.passRate != null && ` · ${Math.round(model.stats.passRate * 100)}% pass`}
          </span>
        </div>
      )}
      <ul className="space-y-0.5">
        {model.levels.map((l) => (
          <LevelRow key={l.index} level={l} open={isOpen(l)}
                    onToggle={() => setPinned((p) => ({ ...p, [l.index]: !isOpen(l) }))} />
        ))}
      </ul>
      {model.paused && (
        <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
          Paused — {model.paused}. Nothing is lost; the next build continues from here.
        </p>
      )}
      {model.ticker.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t pt-2 text-[11px]" aria-label="What the reviewer said">
          {model.ticker.map((t) => (
            <li key={t.seq} className={cn("flex gap-1.5",
                 t.tone === "pass" && "text-green-700", t.tone === "back" && "text-amber-700",
                 t.tone === "retry" && "text-amber-700", t.tone === "wait" && "text-sky-700",
                 t.tone === "note" && "text-muted-foreground")}>
              <span aria-hidden>{t.tone === "pass" ? "✓" : t.tone === "back" ? "↩" : t.tone === "retry" ? "⟳" : t.tone === "wait" ? "…" : "•"}</span>
              <span className="truncate">{t.text}</span>
            </li>
          ))}
        </ul>
      )}
      {model.badges.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {model.badges.map((b) => (
            <span key={b.id} title={b.detail}
                  className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
              <Award className="h-3 w-3" /> {b.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
