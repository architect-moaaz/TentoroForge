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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useBlueprintRun, type RunNode } from "@/hooks/useBlueprintRun";

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

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

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

/**
 * One turn with the architect (§6).
 *
 * `handle_chat_v2` decides a turn and returns it — an answer, a question, or a
 * no-op — so this is a request/response, not a stream. The stream belongs to
 * the generation run, which has its own.
 */
async function askArchitect(
  projectId: string,
  message: string,
): Promise<ArchitectTurn> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const res = await fetch(
    `${API_BASE}/api/projects/${projectId}/smith/chat`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message }),
    },
  );
  // A redirect is not an answer: an expired session returns the login page
  // with status 200, and `res.json()` would throw on HTML.
  if (res.redirected) throw new Error("Not signed in.");
  if (!res.ok) {
    throw new Error(
      res.status === 503
        ? "The architect stack is disabled on the server."
        : `Smith could not answer (HTTP ${res.status}).`,
    );
  }
  return (await res.json()) as ArchitectTurn;
}

export interface SmithPanelProps {
  projectId: string | null;
  /** Told when a run finishes, so the preview pane can refresh itself. */
  onRunComplete?: () => void;
  className?: string;
}

export function SmithPanel({
  projectId,
  onRunComplete,
  className,
}: SmithPanelProps) {
  const { run, start, stop } = useBlueprintRun(projectId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const completedRef = useRef(false);

  // Fire `onRunComplete` once per run, not on every render that follows it.
  useEffect(() => {
    if (run.status === "complete" && !completedRef.current) {
      completedRef.current = true;
      onRunComplete?.();
    }
    if (run.status === "running") completedRef.current = false;
  }, [run.status, onRunComplete]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, run.nodesDone]);

  const busy = run.status === "running" || thinking;

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
  const send = async () => {
    const text = draft.trim();
    if (!text || busy || !projectId) return;
    setDraft("");
    setMessages((m) => [...m, { role: "user", text }]);
    setThinking(true);

    let turn: ArchitectTurn;
    try {
      turn = await askArchitect(projectId, text);
    } catch (e) {
      setThinking(false);
      setMessages((m) => [
        ...m,
        { role: "smith", text: (e as Error).message },
      ]);
      return;
    }
    setThinking(false);

    if (turn.answer) {
      setMessages((m) => [
        ...m,
        {
          role: "smith",
          text: turn.answer,
          options: turn.options,
          diffSummary: turn.diffSummary,
        },
      ]);
    }

    // `handoff` is the architect saying this needs the generator: there is no
    // application yet, or the change is broad enough to rebuild. §25 — hold at
    // the definition either way, so the plan is seen before the dozen calls
    // behind it are spent.
    if (turn.status === "handoff" || turn.status === "no_op") {
      setMessages((m) => [
        ...m,
        {
          role: "smith",
          text: "I'll define this first, then build it once you approve.",
        },
      ]);
      void start({ description: text, approved: false, defineOnly: true });
    }
  };

  const approve = () => {
    const brief = [...messages].reverse().find((m) => m.role === "user");
    if (!brief) return;
    setMessages((m) => [
      ...m,
      { role: "smith", text: "Approved — building the rest of the application." },
    ]);
    void start({ description: brief.text, approved: true });
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

        {messages.map((m, i) => (
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

        {thinking && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            Smith is reading the Blueprint…
          </div>
        )}

        {run.nodes.length > 0 && (
          <StageList run={run} onApprove={approve} />
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
}: {
  run: ReturnType<typeof useBlueprintRun>["run"];
  onApprove: () => void;
}) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-xs font-medium">
          {run.status === "complete"
            ? "Application built"
            : "Building your application"}
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {run.nodesDone}/{run.nodesTotal}
          {run.callsDone > run.nodesDone && ` · ${run.callsDone} calls`}
        </span>
      </div>

      <ul className="space-y-1">
        {run.nodes.map((n) => (
          <StageRow key={n.key} node={n} />
        ))}
      </ul>

      {run.alreadyComplete.length > 0 && (
        // §72 — a resumed run continues rather than redoing. Saying which
        // stages were kept is the difference between "fast" and "skipped".
        <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
          <SkipForward className="h-3 w-3" />
          {run.alreadyComplete.length} stage
          {run.alreadyComplete.length === 1 ? "" : "s"} already complete
        </p>
      )}

      {run.forecast && (
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
            run.forecast?.[key] === undefined ? null : (
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

      {run.awaitingApproval && run.status === "complete" && (
        // §25 — the approval gate. The definition is done and the run is
        // holding; nothing further is spent until this is answered.
        <div className="mt-3 border-t pt-3">
          <p className="text-xs text-muted-foreground">
            The definition is ready. Review it, then build.
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
