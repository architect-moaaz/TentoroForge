"use client";

/**
 * Smith — the architect's pane (§112).
 *
 * The PRD puts Smith in a permanent right-hand column beside the Blueprint and
 * the live application, not behind a tab and not as a step in a wizard. This is
 * that column: a conversation above, the run the conversation started below.
 *
 * IT DRIVES THE BLUEPRINT ENGINE, WHICH IS THE POINT. The product UI has been
 * wired to `routers/generate.py`, which does not import `services.blueprint` at
 * all — so the 20-node DAG, its verification edges and its projections were
 * unreachable from anything a user touches, and the Blueprint was written after
 * the fact from generation output. That inverts §115: the Blueprint is supposed
 * to be what the implementation comes from, not a record of what it turned out
 * to be. `useBlueprintRun` posts to the engine directly.
 *
 * §116 — the lifecycle is deterministic. Smith does not decide the steps; the
 * orchestrator's DAG does, and Smith narrates it. That is why the stage list
 * below renders from the `plan` event rather than from anything a model says.
 *
 * §111 — "Do not expose hidden model reasoning." Each stage shows its name and
 * its state. Nothing streams a model's intermediate thinking into this pane.
 */

import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Circle,
  AlertCircle,
  Send,
  SkipForward,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useBlueprintRun,
  type RunNode,
  type RunEvent as RunEventT,
} from "@/hooks/useBlueprintRun";

/** DAG node keys → the stage names §111 shows a person. */
const STAGE_LABEL: Record<string, string> = {
  requirements: "Requirements",
  application_model: "Product Model",
  ux_architecture: "Application Architecture",
  design_system: "Design System",
  page_contracts: "Page Contracts",
  data_model: "Data Model",
  database: "Database Schema",
  workflows: "Workflows",
  business_rules: "Business Rules",
  security: "Security & Roles",
  integrations: "Integrations",
  apis: "API Surface",
  page_layouts: "Page Design",
  frontend: "Frontend",
  backend: "Backend",
  integration: "Assembly",
  testing: "Tests",
  memory: "Decisions",
  verification: "Verification",
  preview: "Preview",
};

const labelFor = (key: string) => STAGE_LABEL[key] ?? key;

const _BASE_TITLE =
  typeof document !== "undefined" ? document.title : "Tentoro Forge";

/**
 * Say the run has finished, to someone who is probably elsewhere.
 *
 * Permission is never requested unprompted — a permission prompt on page load
 * is the thing everyone denies, and a denial is permanent. Asked only after a
 * run has actually completed, which is the moment the value is obvious.
 */
function notifyDone(awaitingApproval: boolean): void {
  if (typeof window === "undefined") return;

  const text = awaitingApproval
    ? "Your definition is ready to review."
    : "Your application is built.";

  // The tab title works with no permission at all and is what most people
  // will actually see.
  if (document.hidden) document.title = `✓ ${text} — ${_BASE_TITLE}`;

  if (!("Notification" in window)) return;
  const show = () => new Notification("Smith", { body: text });
  if (Notification.permission === "granted") show();
  else if (Notification.permission === "default") {
    void Notification.requestPermission().then(
      (p) => p === "granted" && show(),
    );
  }
}

interface Message {
  role: "user" | "smith";
  text: string;
  /** §16 — the architect asks rather than assumes; these are its choices. */
  options?: string[];
  /** What the turn changed in the Blueprint, if anything. */
  diffSummary?: string;
}

interface ArchitectTurn {
  status: string;
  answer: string;
  options: string[];
  diffSummary: string;
  touchedPaths: string[];
  intent: string | null;
}

export interface SmithPanelProps {
  projectId: string | null;
  /** What Discovery already collected — sent as the opening turn, once. */
  initialBrief?: string;
  /** Text of any requirements documents attached during Discovery (§14). */
  evidence?: string[];
  /** The Blueprint as it stands — §109's Application Definition reads it. */
  blueprint?: Record<string, unknown> | null;
  /** Told when a run finishes, so the preview pane can refresh itself. */
  onRunComplete?: () => void;
  className?: string;
}

export function SmithPanel({
  projectId,
  initialBrief,
  evidence,
  blueprint,
  onRunComplete,
  className,
}: SmithPanelProps) {
  const { run, start, stop } = useBlueprintRun(projectId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);
  const completedRef = useRef(false);

  // Fire `onRunComplete` once per run, not on every render that follows it.
  useEffect(() => {
    if (run.status === "complete" && !completedRef.current) {
      completedRef.current = true;
      onRunComplete?.();
      // A build runs for ten minutes or more, so nobody watches it finish.
      // Told where they actually are rather than only in a pane they have
      // left: the tab title carries it back, and a notification reaches them
      // outside the browser when they have already allowed one.
      notifyDone(run.awaitingApproval);
    }
    if (run.status === "running") completedRef.current = false;
  }, [run.status, run.awaitingApproval, onRunComplete]);

  // Clear the title marker as soon as they look.
  useEffect(() => {
    const restore = () => {
      if (!document.hidden) document.title = _BASE_TITLE;
    };
    document.addEventListener("visibilitychange", restore);
    return () => document.removeEventListener("visibilitychange", restore);
  }, []);

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, run.nodesDone]);

  const busy = run.status === "running";

  // Discovery already asked "what would you like to build?", so the workspace
  // does not ask again — it carries that answer in as the first turn. Guarded
  // by a ref rather than a dependency list: React 18 mounts effects twice in
  // development, and without it the brief is sent to the architect twice.
  const briefSent = useRef(false);
  useEffect(() => {
    if (!initialBrief || !projectId || briefSent.current) return;
    briefSent.current = true;
    setDraft(initialBrief);
  }, [initialBrief, projectId]);

  /**
   * A turn goes to the architect first (§6, §114).
   *
   * Smith decides what the message means — a question to answer, a change to
   * make, or a new application to define — and only the last of those starts
   * the DAG. Sending every message straight to `generate` would make the
   * conversation a build button with a text field, and §114's Prompt-to-Change
   * unreachable: "Add approval for expenses above ₹50,000" is a modification
   * of an existing Blueprint, not a request to build a new app.
   */
  /**
   * Hand the message to Smith. That is the whole of it.
   *
   * This function used to decide: is there a Blueprint, should the architect
   * be consulted, does a `handoff` mean run the graph. §6 makes Smith the
   * Engineering Manager and that routing belongs to it — here it meant a
   * second client would have to reimplement the rules, and they would drift.
   * Smith now streams `message` for what it is doing and the graph's own
   * events when it runs one; this sends and renders.
   */
  const send = () => {
    const text = draft.trim();
    if (!text || busy || !projectId) return;
    setDraft("");
    setMessages((m) => [...m, { role: "user", text }]);
    void start({ description: text, evidence });
  };

  const approve = () => {
    const brief = [...messages].reverse().find((m) => m.role === "user");
    if (!brief) return;
    setMessages((m) => [
      ...m,
      { role: "smith", text: "Approved — building the rest of the application." },
    ]);
    void start({ description: brief.text, evidence, approved: true });
  };

  return (
    <div className={cn("flex h-full flex-col border-l bg-background", className)}>
      <header className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">Smith</h2>
          <p className="text-xs text-muted-foreground">Application architect</p>
        </div>
        {busy && (
          <button
            onClick={stop}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Stop
          </button>
        )}
      </header>

      <div ref={transcriptRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && !busy && (
          <div className="pt-8 text-center">
            <p className="text-sm font-medium">What would you like to build?</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Describe the application. I&apos;ll define it first, then build it
              once you approve.
            </p>
          </div>
        )}

        {[
          ...messages,
          ...run.messages.map((m) => ({
            role: "smith" as const,
            text: m.text,
            options: m.options,
            diffSummary: m.diffSummary,
          })),
        ].map((m, i) => (
          <div
            key={i}
            className={cn(
              "max-w-[90%] rounded-lg px-3 py-2 text-sm",
              m.role === "user"
                ? "ml-auto bg-primary text-primary-foreground"
                : "bg-muted",
            )}
          >
            <p>{m.text}</p>

            {m.diffSummary && (
              // §71 — what the change touched, before it is believed.
              <p className="mt-1 border-t border-current/15 pt-1 text-xs opacity-80">
                {m.diffSummary}
              </p>
            )}

            {m.options && m.options.length > 0 && (
              // §16 — the architect asks rather than assumes. Answering is
              // just another turn, so these send their own label.
              <div className="mt-2 flex flex-wrap gap-1">
                {m.options.map((opt) => (
                  <button
                    key={opt}
                    onClick={() => setDraft(opt)}
                    className="rounded border border-current/25 px-2 py-0.5 text-xs hover:bg-current/10"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}


        {run.status !== "idle" && (
          <StageList run={run} onApprove={approve} definition={blueprint} />
        )}

        {run.status === "error" && (
          <div className="flex items-start gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{run.error}</span>
          </div>
        )}
      </div>

      <div className="border-t p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={2}
            disabled={busy}
            placeholder={
              busy ? "Building…" : "Describe the application, or a change to it"
            }
            className="flex-1 resize-none rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          />
          <button
            onClick={() => void send()}
            disabled={busy || !draft.trim()}
            className="rounded-md bg-primary p-2 text-primary-foreground disabled:opacity-40"
            aria-label="Send"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * The run, as §111 describes it: observable status per stage, and nothing else.
 *
 * Two counts, deliberately separate. `nodesDone/nodesTotal` is progress through
 * the graph; `callsDone` counts executor calls, which a fan-out node multiplies
 * — `page_layouts` makes one per page. Showing calls as nodes is what made an
 * earlier progress display read "44 of 22" and keep climbing.
 */
function StageList({
  run,
  onApprove,
  definition,
}: {
  run: ReturnType<typeof useBlueprintRun>["run"];
  onApprove: () => void;
  definition?: Record<string, unknown> | null;
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-xs font-medium">
          {/*
            A define-only run stops after understanding (§25), and calling that
            "Application built" over six zeros told three different stories in
            one card. What happened is that Smith read the request; say so.
          */}
          {run.awaitingApproval
            ? "Here's what I understood"
            : run.status === "complete"
              ? "Application built"
              : run.status === "running"
                ? "Working on it"
                : "Ready"}
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {run.nodesTotal > 0 && `${run.nodesDone}/${run.nodesTotal}`}
          {run.callsDone > run.nodesDone && ` · ${run.callsDone} calls`}
        </span>
      </div>

      {run.nodes.length === 0 && run.status === "complete" ? (
        // A RESUMED RUN WITH NOTHING TO DO. §72 continues rather than redoes,
        // so a definition that already exists produces an empty plan and a
        // run that finishes in milliseconds. The card was gated on there
        // being stages, so this rendered as silence — indistinguishable from
        // a request that never left the browser, and the approval gate below
        // never appeared for a definition sitting right there.
        <p className="text-xs text-muted-foreground">
          I had already worked this out — nothing needed redoing.
        </p>
      ) : (
        <ul className="space-y-1">
          {run.nodes.map((n) => (
            <StageRow key={n.key} node={n} />
          ))}
        </ul>
      )}

      {run.alreadyComplete.length > 0 && (
        // §72 — a resumed run continues rather than redoing. Saying which
        // stages were kept is the difference between "fast" and "skipped".
        <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
          <SkipForward className="h-3 w-3" />
          {run.alreadyComplete.length} stage
          {run.alreadyComplete.length === 1 ? "" : "s"} already complete
        </p>
      )}

      {run.forecast && Object.values(run.forecast).some((v) => (v ?? 0) > 0) && (
        <dl className="mt-3 grid grid-cols-3 gap-2 border-t pt-3 text-xs">
          {(
            [
              ["pages", "Pages"],
              ["entities", "Entities"],
              ["workflows", "Workflows"],
              ["apis", "APIs"],
              ["businessRules", "Rules"],
              ["expectedTests", "Tests"],
            ] as const
          ).map(([key, label]) =>
            // Zero here means "not planned yet", not "none" — during the
            // definition nothing downstream has run. Showing 0 reads as a
            // failed build to anyone who did not write the pipeline.
            !run.forecast?.[key] ? null : (
              <div key={key}>
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-medium tabular-nums">
                  {run.forecast[key]}
                </dd>
              </div>
            ),
          )}
        </dl>
      )}

      {/*
        No cost line. It was here because the number was captured and unshown,
        and a build reading "$0.23" invites the reader to price their own
        request rather than judge the application — §111 asks for observable
        status, and money is not status. The figure is still in `usage` for
        anyone who wants it in the Activity log.
      */}
      {run.events.length > 0 && <EventLog events={run.events} />}

      {run.awaitingApproval && run.status === "complete" && (
        <Definition doc={definition} />
      )}

      {run.awaitingApproval && run.status === "complete" && (
        // §25 — the approval gate. The definition is done and the run is
        // holding; nothing further is spent until this is answered.
        <div className="mt-3 border-t pt-3">
          <p className="text-xs text-muted-foreground">
            I&apos;ve read your request and written it down. Approving builds
            the application — the pages, the data and the workflows — which
            takes a few minutes.
          </p>
          <button
            onClick={onApprove}
            className="mt-2 w-full rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
          >
            Approve and build
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Every event the engine sent, in order.
 *
 * The stage list is a summary and summaries drop things: an event this build
 * does not model would otherwise be indistinguishable from one that never
 * arrived. Collapsed by default — §111 wants observable status, not a firehose
 * — and it carries no model reasoning, only what the orchestrator announced.
 */
function EventLog({ events }: { events: RunEventT[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 border-t pt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        Activity ({events.length})
      </button>
      {open && (
        <ol className="mt-1 max-h-48 space-y-0.5 overflow-y-auto font-mono text-[11px] leading-relaxed">
          {events.map((e) => (
            <li key={e.seq} className="flex gap-2">
              <span className="shrink-0 text-muted-foreground/60">
                {String(e.seq).padStart(2, "0")}
              </span>
              <span className="text-muted-foreground">{e.detail}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/**
 * §109's Application Definition — what Smith understood, at the moment it asks
 * whether it understood correctly.
 *
 * The approval gate said "Here's what I understood" and then showed a stage
 * list and a cost, so approving was an act of faith: the one thing being
 * approved was the one thing not on screen. The requirements are already in
 * the Blueprint by this point — `requirements` and `application_model` are the
 * two nodes a define-only run executes — so this reads them rather than asking
 * for anything new.
 */
function Definition({ doc }: { doc?: Record<string, unknown> | null }) {
  const reqs = (doc?.requirements as Array<Record<string, unknown>>) ?? [];
  const product = (doc?.product ?? {}) as Record<string, unknown>;
  const app = (doc?.application ?? {}) as Record<string, unknown>;
  const roles = (product.personas ?? product.actors ?? doc?.roles ?? []) as
    Array<Record<string, unknown> | string>;

  if (!reqs.length && !app.description) return null;

  const nameOf = (r: Record<string, unknown> | string) =>
    typeof r === "string" ? r : String(r.name ?? r.role ?? r.id ?? "");

  return (
    <div className="mt-3 border-t pt-3">
      {typeof app.description === "string" && app.description && (
        <p className="text-xs leading-relaxed">{app.description}</p>
      )}

      {roles.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          For {roles.map(nameOf).filter(Boolean).join(", ")}
        </p>
      )}

      {reqs.length > 0 && (
        <>
          <p className="mt-3 text-xs font-medium">
            What it needs to do ({reqs.length})
          </p>
          <ul className="mt-1 space-y-1">
            {reqs.map((r, i) => (
              <li key={String(r.id ?? i)} className="flex gap-1.5 text-xs">
                <span className="text-muted-foreground/50">·</span>
                <span>{String(r.description ?? r.name ?? r.id ?? "")}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            Anything missing or wrong? Tell me below and I&apos;ll change it
            before building.
          </p>
        </>
      )}
    </div>
  );
}

/** "1m 33s", not "93s" — seconds past a minute stop being readable. */
function _duration(secs: number): string {
  const s = Math.round(secs);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function StageRow({ node }: { node: RunNode }) {
  const Icon =
    node.state === "done"
      ? CheckCircle2
      : node.state === "running"
        ? Loader2
        : Circle;

  return (
    <li className="flex items-center gap-2 text-xs">
      <Icon
        className={cn(
          "h-3.5 w-3.5 shrink-0",
          node.state === "done" && "text-green-600",
          node.state === "running" && "animate-spin text-primary",
          node.state === "waiting" && "text-muted-foreground/40",
        )}
      />
      <span
        className={cn(
          node.state === "waiting" && "text-muted-foreground",
          node.state === "done" && "text-foreground",
        )}
      >
        {labelFor(node.key)}
      </span>
      {node.subject && (
        <span className="truncate text-muted-foreground">{node.subject}</span>
      )}
    </li>
  );
}

export default SmithPanel;
