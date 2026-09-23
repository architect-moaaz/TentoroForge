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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * The engine's origin. The greeting fetch below was relative, so it resolved
 * against the Next dev server on :6501 rather than the API on :6500, which
 * has no such route and answers 401. Smith therefore opened on the fixed
 * fallback sentence for everyone, and the greeting that knows the project
 * — the whole point of §107 step 1 — was never once seen.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Image as ImageIcon,
  ListChecks,
  Loader2,
  Mic,
  Paperclip,
  Send,
  SkipForward,
  XCircle,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { MarkdownLink } from "@/components/chat/MarkdownLink";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { ReviewWindow } from "@/components/smith/ReviewWindow";
import { STAGE_VERB, labelFor } from "./stages";
import { OfficeStrip } from "./OfficeStrip";
import { useOfficeStore } from "@/components/virtual-office";
import {
  AppTile,
  BlueprintSummary,
  blueprintCountsLine,
  blueprintName,
  type BlueprintStatus,
} from "./BlueprintSummary";
import {
  useBlueprintRun,
  type RunNode,
  type RunEvent as RunEventT,
  type RunThought,
  type BlueprintRun,
} from "@/hooks/useBlueprintRun";

/** §107 step 1 — what Smith says before the user says anything. */
type Greeting = {
  state: string;
  headline: string;
  detail: string;
  nextAct: string;
  openers: { kind: string; example: string }[];
  facts: Record<string, unknown>;
};

/** DAG node keys → the stage names §111 shows a person. */
/**
 * What Smith is doing, as an action rather than a noun.
 *
 * A build runs for ten minutes behind a row of stage names that do not move.
 * A present participle says the machine is working on something specific,
 * which is the difference between waiting and wondering whether it hung.
 */
/** Messages sent with each turn — Smith reads the last six; a little slack. */
const SENT_HISTORY = 10;


/** `4m 12s`, or `48s` — a duration a person reads at a glance. */
function human(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`
                 : `${s}s`;
}



const _BASE_TITLE =
  typeof document !== "undefined" ? document.title : "Tentoro Forge";

/**
 * Say the run has finished, to someone who is probably elsewhere.
 *
 * Permission is never requested unprompted — a permission prompt on page load
 * is the thing everyone denies, and a denial is permanent. Asked only after a
 * run has actually completed, which is the moment the value is obvious.
 */
function notifyDone(awaitingApproval: boolean, ranAnything: boolean): void {
  if (typeof window === "undefined") return;

  // NOTHING RAN, SO THERE IS NOTHING TO ANNOUNCE. A turn that plans zero
  // nodes still completes, and this told everyone their application had been
  // built — after a question that was answered without touching it. The tab
  // title said "✓ Your application is built" for a run that did nothing at
  // all, which is the one claim a completion notice must never make falsely:
  // its whole purpose is to be believed by someone who was not watching.
  //
  // A definition already waiting is different and still worth saying: the
  // work was done earlier, and the thing being announced is that it is ready
  // to look at.
  if (!ranAnything && !awaitingApproval) return;

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
  /** When the turn arrived, so the transcript reads as a conversation.
   *  Client-side: the server persists no turn, so there is no other clock. */
  at?: number;
  /**
   * A finished run's plan, kept where it happened.
   *
   * `start()` resets the run to EMPTY, so the next message erased the last
   * run's stages — and the approval gate with them. The run is a live thing
   * and the transcript is the durable one, so a completed plan is folded in
   * here rather than left in state that the following turn clears.
   */
  plan?: BlueprintRun;
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

/**
 * Smith's side of the conversation, rendered as light markdown.
 *
 * Smith answers about an application by naming its screens, routes, fields
 * and requirements, and a paragraph that names six of them in a row is a
 * wall. The backend now writes a one-line lead and a list where there is a
 * list, with the names in bold; this is where that structure becomes
 * visible. Compact on purpose — the bubble is a chat message, not a
 * document — so headings are flattened to bold and lists sit tight.
 */
function SmithProse({ text }: { text: string }) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none text-sm leading-relaxed text-foreground",
        "[&_p]:my-1.5 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0",
        "[&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-4",
        "[&_li]:my-0.5 [&_li]:pl-0.5 [&_li>p]:my-0",
        "[&_strong]:font-semibold [&_strong]:text-foreground",
        "[&_code]:rounded [&_code]:bg-background/70 [&_code]:px-1 [&_code]:py-0 [&_code]:text-[0.85em] [&_code]:font-normal",
        "[&_code]:before:content-none [&_code]:after:content-none",
        "[&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-sm [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold",
        "[&_h1]:my-1.5 [&_h2]:my-1.5 [&_h3]:my-1.5",
        "[&_a]:underline [&_blockquote]:my-1.5 [&_blockquote]:border-l-2 [&_blockquote]:pl-2 [&_blockquote]:not-italic",
        "[&_table]:my-1.5 [&_table]:text-xs [&_th]:py-0.5 [&_td]:py-0.5",
      )}
    >
      {/* `a` is overridden so an export link downloads with the platform's
          Bearer token — a plain href comes back 401. Every other link is
          untouched. See MarkdownLink. */}
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: MarkdownLink }}>
        {text}
      </ReactMarkdown>
    </div>
  );
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
  const [greeting, setGreeting] = useState<Greeting | null>(null);
  const [draft, setDraft] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);
  const completedRef = useRef(false);

  // Fire `onRunComplete` once per run, not on every render that follows it.
  useEffect(() => {
    if (run.status === "complete" && !completedRef.current) {
      completedRef.current = true;
      // Snapshotted before anything can start another run and reset it.
      if (run.nodes.length > 0 || run.awaitingApproval) {
        setMessages((m) => [...m, { role: "smith", text: "", at: Date.now(),
                                    plan: run }]);
        // AND KEEP IT OPEN. Without this the panel empties the moment a run
        // finishes, so the definition and its Approve button disappear until
        // somebody thinks to click the marker — the same vanishing gate this
        // work set out to fix, reintroduced by moving it. The marker stays
        // clickable for older runs; this only decides what is showing now.
        setOpenPlan(run);
      }
      onRunComplete?.();
      // A build runs for ten minutes or more, so nobody watches it finish.
      // Told where they actually are rather than only in a pane they have
      // left: the tab title carries it back, and a notification reaches them
      // outside the browser when they have already allowed one.
      notifyDone(run.awaitingApproval, run.nodesTotal > 0);
      // PULL THE TRAILING MESSAGES THE STREAM COULD NOT DELIVER. A long build
      // drops its SSE and the panel polls the run registry, which carries node
      // states but not messages — so the "your application is built" line and
      // the "verify & fix" offer, emitted after the drop, are persisted to the
      // transcript but never streamed here. Without this they appear only on a
      // manual reload; the user saw the build finish and no offer. Fetch the
      // transcript and append whatever is not already shown (deduped by
      // role+text, so a message that WAS streamed is not doubled).
      if (projectId) {
        void (async () => {
          try {
            const token =
              typeof window !== "undefined" ? localStorage.getItem("token") : null;
            const res = await fetch(
              `${API_BASE}/api/projects/${projectId}/conversations`,
              {
                credentials: "include",
                headers: token ? { Authorization: `Bearer ${token}` } : {},
              },
            );
            if (!res.ok) return;
            const rows = (await res.json()) as Array<Record<string, unknown>>;
            if (!Array.isArray(rows)) return;
            setMessages((cur) => {
              const seen = new Set(cur.map((m) => `${m.role}\u0000${m.text}`));
              const add = rows
                .filter((r) => String(r.content ?? "").trim())
                .map((r) => {
                  const meta = (r.metadata ?? {}) as Record<string, unknown>;
                  return {
                    role: r.role === "user" ? ("user" as const) : ("smith" as const),
                    text: String(r.content ?? ""),
                    options: (meta.options as string[]) ?? undefined,
                    diffSummary: (meta.diffSummary as string) || undefined,
                    at: r.created_at ? Date.parse(String(r.created_at)) : Date.now(),
                  };
                })
                .filter((m) => !seen.has(`${m.role}\u0000${m.text}`));
              return add.length ? [...cur, ...add] : cur;
            });
          } catch {
            /* a missed sync is not an error — a reload still recovers it */
          }
        })();
      }
    }
    if (run.status === "running") {
      completedRef.current = false;
      // AND HAND THE PANEL BACK TO THE LIVE RUN. A finished run is pinned
      // open so its approval gate does not vanish, but pinning it also meant
      // the next build had nowhere to appear: approving showed the definition
      // that had just been approved, while twenty stages ran unseen behind it.
      setOpenPlan(null);
    }
  }, [run.status, run.awaitingApproval, onRunComplete, projectId]);

  /**
   * §107 step 1 — Smith speaks first.
   *
   * The pane used to open on a fixed "What would you like to build?", which is
   * the right question exactly once. §118 calls Smith the persistent architect,
   * and a user returning to an application with eighteen pages parked at the
   * build gate was being asked what they would like to build. The endpoint is
   * deterministic and reads only the document and §94's state, so this is a
   * cheap call on mount rather than a model turn.
   */
  useEffect(() => {
    if (!projectId) return;
    let live = true;
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    const headers: Record<string, string> = token
      ? { Authorization: `Bearer ${token}` }
      : {};
    fetch(`${API_BASE}/api/projects/${projectId}/smith/greeting`, {
      credentials: "include",
      headers,
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((g) => live && setGreeting(g))
      // The fixed sentence below is the fallback, so a failure here costs the
      // returning user their bearings and nobody else anything.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [projectId]);

  // Clear the title marker as soon as they look.
  useEffect(() => {
    const restore = () => {
      if (!document.hidden) document.title = _BASE_TITLE;
    };
    document.addEventListener("visibilitychange", restore);
    return () => document.removeEventListener("visibilitychange", restore);
  }, []);

  // Follows the thinking as well as the messages: the reasoning block grows
  // at the bottom of the transcript while a turn runs, and a block the
  // transcript does not scroll to is a block nobody sees.
  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, run.nodesDone, run.thoughts.length]);

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
  /**
   * ONE TRANSCRIPT, IN ARRIVAL ORDER.
   *
   * Smith's turns arrived over SSE in `run.messages` and were rendered by
   * concatenating the two lists — `[...messages, ...run.messages]` — which
   * groups every user turn above every Smith turn rather than interleaving
   * them. With one exchange that is indistinguishable from correct; from the
   * second turn on it is not. Asking a follow-up put the question above the
   * reply to the previous message, so the conversation read as though Smith
   * had answered something nobody asked.
   *
   * Neither list could be sorted against the other: local turns have no
   * sequence and `run.messages` restarts at zero every run. So they are not
   * merged at render time at all — Smith's turns are copied into the same
   * list the user's turns go into, as they arrive, and order is simply the
   * order things happened.
   */
  /**
   * §8 layer 1 — the conversation, from where it is kept.
   *
   * The transcript lived only in this component, so opening a project showed
   * a blank pane however long its history was, and leaving the page threw the
   * exchange away. Smith now writes each turn to the project's conversation;
   * this reads it back so the panel opens where it left off.
   *
   * Once, on mount, and only into an empty transcript: a run in progress is
   * already streaming turns in, and merging a fetch into that would duplicate
   * whatever arrived while it was in flight.
   */
  const loadedRef = useRef(false);
  useEffect(() => {
    if (!projectId || loadedRef.current) return;
    loadedRef.current = true;
    let live = true;
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    const headers: Record<string, string> = token
      ? { Authorization: `Bearer ${token}` }
      : {};
    fetch(`${API_BASE}/api/projects/${projectId}/conversations`, {
      credentials: "include",
      headers,
    })
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: Array<Record<string, unknown>>) => {
        if (!live || !Array.isArray(rows) || rows.length === 0) return;
        const past: Message[] = rows
          .filter((r) => String(r.content ?? "").trim())
          .map((r) => {
            const meta = (r.metadata ?? {}) as Record<string, unknown>;
            return {
              role: r.role === "user" ? ("user" as const) : ("smith" as const),
              text: String(r.content ?? ""),
              at: r.created_at ? Date.parse(String(r.created_at)) : undefined,
              options: (meta.options as string[]) ?? undefined,
              diffSummary: (meta.diffSummary as string) || undefined,
            };
          });
        setMessages((m) => (m.length ? m : past));
      })
      .catch(() => undefined);
  }, [projectId]);

  /**
   * §5 — an application can be described by SHOWING as well as by telling.
   *
   * The whole path already existed and had no door: an upload becomes an
   * attachment, `PUT /design-references` designates it as direction rather
   * than a bug report, `_adopt_design_references` copies it into
   * `.forge/references/`, and the requirements and application-model agents
   * read it as an image. Nothing in the product let anyone attach one, so an
   * application described by screenshot was, to every agent, an application
   * described by silence.
   */
  /**
   * Which plan the side panel is showing.
   *
   * Smith's work belongs beside the conversation, not inside it: a
   * twenty-stage plan rendered as a chat bubble pushes the exchange off the
   * screen, and the run you care about is rarely the last thing said. The
   * transcript keeps a one-line marker per plan and this decides which one is
   * open. `null` follows the live run, so a build in progress is what you see
   * without having to ask for it.
   */
  const [openPlan, setOpenPlan] = useState<BlueprintRun | null>(null);
  // "Edit blueprint" on the right means "tell Smith": the definition is
  // changed by talking, so the button brings the cursor here.
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const [shown, setShown] = useState<{ id: string; name: string }[]>([]);
  const [listening, setListening] = useState(false);

  const attach = async (files: File[]) => {
    if (!projectId || files.length === 0) return;
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    const headers: Record<string, string> = token
      ? { Authorization: `Bearer ${token}` }
      : {};
    const added: { id: string; name: string }[] = [];
    for (const f of files) {
      const body = new FormData();
      body.append("file", f);
      try {
        const r = await fetch(
          `${API_BASE}/api/projects/${projectId}/attachments`,
          { method: "POST", headers, credentials: "include", body },
        );
        if (!r.ok) continue;
        const rec = await r.json();
        if (rec?.id) added.push({ id: String(rec.id), name: f.name });
      } catch {
        /* one attachment that will not upload is not a failed conversation */
      }
    }
    if (added.length === 0) return;
    const next = [...shown, ...added];
    setShown(next);
    // DESIGNATED, not merely uploaded. Most attachments are bug reports;
    // designation is how someone says this one is direction, and it is what
    // the generation reads.
    try {
      await fetch(`${API_BASE}/api/projects/${projectId}/design-references`, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ attachment_ids: next.map((a) => a.id) }),
      });
    } catch {
      /* the upload survived; the designation can be retried by re-attaching */
    }
  };

  /**
   * §5 again — speaking is a way of telling.
   *
   * Browser-native recognition rather than a service: it needs no key, no
   * audio leaves the machine on Firefox-class engines, and a mic that works
   * offline beats one that needs a round trip to say "hello". Absent support
   * hides the button rather than offering one that does nothing.
   */
  const dictate = () => {
    const w = window as unknown as {
      SpeechRecognition?: new () => any;
      webkitSpeechRecognition?: new () => any;
    };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    // Appended to whatever is already typed, so dictation adds a sentence to
    // a draft rather than replacing it.
    const base = draft;
    rec.onresult = (e: any) => {
      let heard = "";
      for (let i = 0; i < e.results.length; i++) heard += e.results[i][0].transcript;
      setDraft((base ? base.replace(/\s*$/, " ") : "") + heard);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    setListening(true);
    rec.start();
  };

  const canDictate =
    typeof window !== "undefined" &&
    Boolean(
      (window as unknown as Record<string, unknown>).SpeechRecognition ??
        (window as unknown as Record<string, unknown>).webkitSpeechRecognition,
    );

  const copiedRef = useRef(0);
  useEffect(() => {
    // A new run empties `run.messages`; what was already copied stays in the
    // transcript, so the counter restarts alongside it.
    if (run.messages.length < copiedRef.current) copiedRef.current = 0;
    if (run.messages.length === copiedRef.current) return;
    const fresh = run.messages.slice(copiedRef.current);
    copiedRef.current = run.messages.length;
    setMessages((m) => [
      ...m,
      ...fresh.map((x) => ({
        role: "smith" as const,
        text: x.text,
        options: x.options,
        diffSummary: x.diffSummary,
        at: Date.now(),
      })),
    ]);
  }, [run.messages]);

  // Split out so a turn can be sent by something other than the composer —
  // the Figma import hands one in below, and it must go through exactly the
  // same path a typed message does or it is a second way to talk to Smith.
  // THE OPEN QUESTIONS: Smith's trailing messages that carry options, after
  // the last thing the user said. Answered ones are remembered until the set
  // is sent; a new user message closes the set.
  const [questionAnswers, setQuestionAnswers] = useState<Record<number, string>>({});
  const openQuestions = useMemo(() => {
    const out: number[] = [];
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "user") break;
      if (m.options && m.options.length > 0) out.unshift(i);
    }
    return out;
  }, [messages]);
  const firstUnanswered = openQuestions.findIndex((i) => !questionAnswers[i]);
  const answerQuestion = (index: number, answer: string) => {
    const next = { ...questionAnswers, [index]: answer };
    setQuestionAnswers(next);
    if (openQuestions.every((i) => next[i])) {
      const reply = openQuestions
        .map((i) => `${messages[i].text.trim()} ${next[i]}`)
        .join("\n");
      setQuestionAnswers({});
      sendText(openQuestions.length === 1 ? next[openQuestions[0]] : reply);
    }
  };

  const sendText = useCallback(
    (text: string) => {
      if (!text || !projectId) return;
      // Taken BEFORE the new turn is appended: the history is what came before
      // this message, and including the message in its own history would have
      // Smith read the question as its own answer.
      // Only the recent exchange travels: Smith reads the last few turns (a
      // question and its answer are adjacent), and an ask it could not act on
      // is carried on the server (`pending_ask`). The whole transcript went
      // with every message and was dropped there.
      const prior = messages.slice(-SENT_HISTORY).map((m) => ({ role: m.role, text: m.text }));
      setMessages((m) => [...m, { role: "user", text, at: Date.now() }]);
      void start({ description: text, evidence, history: prior });
    },
    [projectId, messages, evidence, start],
  );

  const send = () => {
    const text = draft.trim();
    if (!text || busy || !projectId) return;
    setDraft("");
    sendText(text);
  };

  // THE FIGMA IMPORT LANDS HERE.
  //
  // `NewAppDialog` writes `figma_connect_<projectId>` and navigates. The
  // brief and the design go to Smith as ONE opening message: the router finds
  // the link in the brief, asks its clarifying questions knowing a design is
  // attached, runs the definition, and attaches the design in the same turn.
  //
  // A held trigger used to send the connect when "the run completed" — and a
  // clarifying question completes a turn, so on 2026-09-05 the connect went
  // out before the definition, Smith answered "let me define that first",
  // and the design was never fetched. There is nothing to time any more.
  useEffect(() => {
    if (!projectId) return;
    // `design_connect_` carries either provider; `figma_connect_` is the
    // older key a tab may still hold.
    const key = `design_connect_${projectId}`;
    const legacyKey = `figma_connect_${projectId}`;
    const raw = sessionStorage.getItem(key) ?? sessionStorage.getItem(legacyKey);
    if (!raw) return;
    sessionStorage.removeItem(key);
    sessionStorage.removeItem(legacyKey);
    try {
      const parsed = JSON.parse(raw);
      const provider: string = parsed.provider === "uxpilot" ? "uxpilot" : "figma";
      const ref: string = String(parsed.ref || parsed.figma_url || "").trim();
      const scope = parsed.treat_as === "specification" ? "the specification" : "a reference";
      // The credential is named, never pasted (§42): the message tells Smith
      // which environment variable holds it, and the server resolves the
      // value from the organisation's integrations at the moment of the call.
      const connect = !ref
        ? ""
        : provider === "uxpilot"
          ? `Connect this UX Pilot page as ${scope}: ${ref} — the API key ` +
            `is in the environment variable UXPILOT_API_KEY.`
          : `Connect this Figma design as ${scope}: ${ref} — the access token ` +
            `is in the environment variable FIGMA_TOKEN.`;
      const opening = [String(parsed.brief || "").trim(), connect]
        .filter(Boolean).join("\n\n");
      if (opening) sendText(opening);
    } catch {
      // A malformed trigger is not worth a broken panel.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const approve = () => {
    // THE BRIEF MAY NOT BE IN MEMORY. After a reload — or after any later turn
    // — the last user message can be a clarification answer or nothing at all,
    // and this returned silently, so the button did nothing. The Blueprint's
    // own description is the brief the definition was built from.
    const spoken = [...messages].reverse().find((m) => m.role === "user");
    const described = String(
      ((blueprint as { application?: { description?: unknown } } | null | undefined)
        ?.application?.description) ?? "",
    ).trim();
    const brief = spoken ?? (described ? { text: described } : null);
    if (!brief) return;
    setMessages((m) => [
      ...m,
      { role: "smith", text: "Approved — building the rest of the application.",
        at: Date.now() },
    ]);
    void start({ description: brief.text, evidence, approved: true });
  };

  // A definition exists and nothing has been built from it. Read off the
  // Blueprint so it survives reloads and later turns, unlike `awaitingApproval`.
  // "Not built" means FEWER LAYOUTS THAN PAGES, not zero layouts. A run that
  // failed partway leaves some pages composed and the rest not — 4 of 15 on a
  // real project — and demanding zero hid the gate on exactly the project
  // that most needed a way to finish. A fresh definition has no pages yet, so
  // the floor of one keeps it showing there too.
  const bp = (blueprint ?? {}) as Record<string, unknown>;
  const pageCount = (bp.pages as unknown[] | undefined)?.length ?? 0;
  const layoutCount = (bp.pageLayouts as unknown[] | undefined)?.length ?? 0;
  // THE GATE CLEARS ONCE THE APP HAS BEEN BUILT. A preview build that ran
  // (`runtime.build`) means the application exists — a handful of pages the
  // composer never managed are missing routes that 404, not a reason to force
  // the "Finish the missing pages" screen forever. Left as `layoutCount <
  // pageCount` alone, any page that deterministically fails to compose kept
  // that true for good: the gate reappeared after every run, and each click
  // fired another full (Opus) page_layouts fan-out — which is how one app ran
  // up ~$40 chasing eleven pages that were never going to compose. A
  // never-built definition (no `runtime.build`) still shows the gate, so a
  // first build is still offered.
  const alreadyBuilt = Boolean(
    (bp.runtime as { build?: unknown } | undefined)?.build,
  );
  const definedNotBuilt =
    !busy &&
    Array.isArray(bp.requirements) &&
    (bp.requirements as unknown[]).length > 0 &&
    layoutCount < Math.max(pageCount, 1) &&
    !alreadyBuilt;

  // Whether there is a definition to show at all, and where it stands. The
  // summary reads the document; this decides which of its footers it gets.
  const hasDefinition =
    (Array.isArray(bp.requirements) && (bp.requirements as unknown[]).length > 0) ||
    pageCount > 0;
  const summaryStatus: BlueprintStatus = busy
    ? { kind: "building" }
    : definedNotBuilt
      ? layoutCount === 0
        ? { kind: "ready" }
        : { kind: "partial", missing: pageCount - layoutCount, total: pageCount }
      : { kind: "built" };

  // What the side panel is showing: the run you picked, or the live one.
  const sidePlan =
    openPlan ??
    (run.status === "running" ||
    (run.status === "complete" && !completedRef.current)
      ? run
      : null);

  return (
    <div className={cn("flex h-full min-w-0", className)}>
    {/* Smith's live render review — a fixed bottom-right window while it looks
        at what it built; renders nothing until a review starts. */}
    <ReviewWindow review={run.review} />
    <div className="flex h-full min-w-0 flex-1 flex-col border-l bg-background">
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
            <p className="text-sm font-medium">
              {greeting?.headline ?? "What would you like to build?"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {greeting?.detail ??
                "Describe the application. I'll define it first, then build it once you approve."}
            </p>
            {greeting?.nextAct && (
              <p className="mt-2 text-xs font-medium">{greeting.nextAct}</p>
            )}
            {/* Only when there is nothing yet: a user with an application
                does not need to be told what kinds of application exist. */}
            {!!greeting?.openers?.length && (
              <ul className="mx-auto mt-4 max-w-sm space-y-1 text-left">
                {greeting.openers.map((o) => (
                  <li key={o.kind} className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{o.kind}</span>
                    {" — "}
                    {o.example}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {messages.map((m, i) => (
          <div
            key={i}
            className={cn("max-w-[90%]", m.role === "user" && "ml-auto")}
          >
            {/*
              WHO SAID IT AND WHEN. The transcript was bare bubbles, so a
              returning reader could not tell Smith's turns from their own
              except by which side they sat on, and had no idea whether an
              exchange happened a minute or a day ago. Repeated speakers are
              not relabelled — a run of Smith's turns reads as one voice.
            */}
            {!m.plan && (i === 0 || messages[i - 1].role !== m.role) && (
              <div
                className={cn(
                  "mb-1 flex items-baseline gap-2 text-xs",
                  m.role === "user" && "justify-end",
                )}
              >
                <span className="font-medium">
                  {m.role === "user" ? "You" : "Smith"}
                </span>
                {m.at && (
                  <span className="tabular-nums text-muted-foreground">
                    {new Date(m.at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                )}
              </div>
            )}
            {m.plan?.awaitingApproval ? (
              // THE BLUEPRINT'S CARD. A definition is the one plan whose
              // outcome is a thing rather than a run, so its marker names the
              // application and what it holds, and opens the Blueprint on the
              // right rather than a stage list.
              <button
                type="button"
                onClick={() => setOpenPlan(m.plan ?? null)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl border bg-card px-3 py-2.5 text-left hover:bg-muted/60",
                  openPlan === m.plan && "border-primary",
                )}
              >
                <AppTile doc={blueprint} className="h-11 w-11 text-lg" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {blueprintName(blueprint)}
                  </span>
                  <span className="block text-xs text-muted-foreground">App Blueprint</span>
                  <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                    {blueprintCountsLine(blueprint)}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                  View on right
                  <ArrowRight className="h-3.5 w-3.5" />
                </span>
              </button>
            ) : m.plan ? (
              // A MARKER, NOT THE PLAN ITSELF. Clicking it opens that run on
              // the right, where there is room for it.
              <button
                type="button"
                onClick={() => setOpenPlan(m.plan ?? null)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted",
                  openPlan === m.plan && "border-primary bg-muted",
                )}
              >
                <ListChecks className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="font-medium">
                  {m.plan.nodesTotal > 0
                    ? `Built in ${m.plan.nodesTotal} stages`
                    : "Nothing needed doing"}
                </span>
                <span className="ml-auto text-muted-foreground">
                  {m.at &&
                    new Date(m.at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                </span>
              </button>
            ) : (
            <div
              className={cn(
                "rounded-lg px-3 py-2 text-sm",
                m.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted",
              )}
            >
            {m.role === "user" ? (
              <p className="whitespace-pre-wrap">{m.text}</p>
            ) : (
              <SmithProse text={m.text} />
            )}

            {m.diffSummary && (
              // §71 — what the change touched, before it is believed.
              <p className="mt-1 border-t border-current/15 pt-1 text-xs opacity-80">
                {m.diffSummary}
              </p>
            )}

            {m.options && m.options.length > 0 && (
              // §16 — the architect asks rather than assumes. Answering is
              // just another turn, so these SEND their own label.
              //
              // ONE QUESTION AT A TIME. Smith may ask three at once, each its
              // own message. When every question showed its chips, the first
              // chip clicked sent that answer alone, the turn ended, and the
              // other two questions were never answered — the answer to the
              // last one overrode the rest. Only the first unanswered question
              // of the open set offers its chips; an answer is kept here and
              // the next question opens; the last answer sends them all in
              // one reply, which is what the clarifier expects.
              (() => {
                const idx = openQuestions.indexOf(i);
                if (idx < 0) return null; // an old question, already answered
                const answered = questionAnswers[i];
                if (answered) {
                  return (
                    <p className="mt-2 text-xs text-muted-foreground">
                      <span className="rounded border border-current/25 bg-current/10 px-2 py-0.5">{answered}</span>
                    </p>
                  );
                }
                if (idx !== firstUnanswered) return null; // its turn comes next
                return (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {m.options.map((opt) => (
                      <button
                        key={opt}
                        disabled={busy}
                        onClick={() => answerQuestion(i, opt)}
                        className="rounded border border-current/25 px-2 py-0.5 text-xs hover:bg-current/10"
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                );
              })()
            )}
            </div>
            )}
          </div>
        ))}

        <ThinkingTrail thoughts={run.thoughts} nodes={run.nodes} busy={busy} />

        {run.status === "error" && (
          <div className="flex items-start gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{run.error}</span>
          </div>
        )}
      </div>

      <div className="border-t p-3">
        {shown.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1">
            {shown.map((a) => (
              <span
                key={a.id}
                className="flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-xs"
                title="Read as design direction by the next generation"
              >
                <ImageIcon className="h-3 w-3" />
                {a.name}
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
          <label
            className="cursor-pointer rounded-md border p-2 text-muted-foreground hover:bg-muted"
            title="Attach a screenshot, a design, or a spreadsheet to load in"
          >
            <Paperclip className="h-4 w-4" />
            {/* A SPREADSHEET IS THE POINT OF THE PAPERCLIP for an owner who
                already has a business: they attach customers.xlsx and say
                "load it in" (services/smith/data_import.py). Leaving the sheet
                formats out of this list made the import unreachable from the
                panel it is driven from. */}
            <input
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp,image/gif,.txt,.md,.markdown,.csv,.tsv,.xlsx"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                void attach(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
          </label>
          {canDictate && (
            <button
              type="button"
              onClick={dictate}
              disabled={busy || listening}
              aria-label="Dictate"
              title="Speak instead of typing"
              className={cn(
                "rounded-md border p-2 hover:bg-muted",
                listening
                  ? "animate-pulse border-primary text-primary"
                  : "text-muted-foreground",
              )}
            >
              <Mic className="h-4 w-4" />
            </button>
          )}
          <textarea
            ref={composerRef}
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

    {/*
      SMITH'S WORK, BESIDE THE CONVERSATION.

      A twenty-stage plan rendered as a chat bubble pushed the exchange off
      the screen, and the run somebody cares about is rarely the last thing
      said. So the transcript keeps a marker per plan and the plan itself
      lives here, where there is room for its stages, its definition and its
      approval gate.

      Hidden below `lg` rather than made narrower: this panel also renders as
      a 380px sidebar on the Blueprint page, and two columns in that is two
      unreadable ones. There the plan opens in place, as it did before.
    */}
    {/*
      A SHARE OF THE WIDTH, NOT A FIXED ONE. At 460px the column took more
      than a third of a 1280px workspace and squeezed the conversation into
      less than the Blueprint; below 360px the card's two-column rows broke.
      So it takes just over a third of what is available, between those bounds.
    */}
    <aside className="hidden w-[clamp(360px,36%,440px)] shrink-0 flex-col border-l bg-muted/30 lg:flex">
      {sidePlan &&
      !(sidePlan.awaitingApproval && sidePlan.status === "complete") ? (
        // A RUN IN PROGRESS, OR ONE PICKED FROM THE TRANSCRIPT: its stages.
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {openPlan && (
            <button
              type="button"
              onClick={() => setOpenPlan(null)}
              className="mb-2 text-xs text-muted-foreground hover:text-foreground"
            >
              ← Back to the current run
            </button>
          )}
          <StageList run={sidePlan} />
        </div>
      ) : hasDefinition ? (
        // THE BLUEPRINT. Read off the document rather than the run, so a
        // reload or a later turn — connecting a design, answering a question
        // — does not hide the definition or the way to say yes to it. That
        // is what used to leave the panel with no plan and no approval
        // control: the definition was finished and nothing could start.
        <>
          {openPlan && run.status === "running" && (
            <button
              type="button"
              onClick={() => setOpenPlan(null)}
              className="px-4 pt-3 text-left text-xs text-muted-foreground hover:text-foreground"
            >
              ← Back to the current run
            </button>
          )}
          <BlueprintSummary
            doc={bp}
            status={summaryStatus}
            onBuild={approve}
            onEdit={() => composerRef.current?.focus()}
            className="min-h-0 flex-1"
          />
        </>
      ) : sidePlan?.awaitingApproval ? (
        // The define run has finished and the document is on its way.
        <p className="mt-8 flex items-center justify-center gap-2 px-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading the definition…
        </p>
      ) : (
        <p className="mt-8 px-2 text-center text-xs text-muted-foreground">
          What Smith does appears here — the plan it follows, the stages as
          they run, and the Blueprint it asks you to approve.
        </p>
      )}
    </aside>
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
}: {
  run: ReturnType<typeof useBlueprintRun>["run"];
}) {
  // WHEN THIS RUN BEGAN, and a clock that moves. Elapsed time read from a
  // static render would freeze at whatever it was when a node last landed —
  // which is exactly the moment a watcher starts wondering if it hung.
  const startedAt = useRef<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  if (run.status === "running" && startedAt.current === null) {
    // A reattached run did not begin when this component mounted. Seeding the
    // clock from the server's elapsed keeps "21m 06s" from restarting at zero
    // on every reload, which would read as a run that keeps starting over.
    startedAt.current =
      Date.now() - (run.reattachedElapsedMs ?? 0);
  }
  useEffect(() => {
    if (run.status !== "running") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [run.status]);
  const started = startedAt.current;
  // The office outlives the request that started the run by a few frames
  // (the celebration, whoever stayed parked); keyed on the run alone the
  // strip vanished at exactly the moment there was something to look at.
  const officeRunActive = useOfficeStore((s) => s.runActive);

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
              ? // A turn can complete having planned nothing — a question
                // answered from the Blueprint, or a §72 resume with nothing
                // left to do. The body below already says nothing needed
                // redoing; the heading used to contradict it.
                run.nodesTotal > 0
                ? "Application built"
                : "Nothing needed doing"
              : run.status === "running"
                ? "Working on it"
                : "Ready"}
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {run.nodesTotal > 0 && `${run.nodesDone}/${run.nodesTotal}`}
          {run.callsDone > run.nodesDone && ` · ${run.callsDone} calls`}
        </span>
      </div>

      {/*
        HOW FAR, HOW LONG, AND WHAT IT IS DOING. A ten-minute build showed a
        static list of stage names, so there was no way to tell progress from
        a hang.

        The estimate comes from THIS run's own pace — elapsed divided by
        stages finished, times stages left — rather than from a stored average.
        Nothing persists a previous run's timing yet, and a remaining-time
        figure derived from the run you are watching cannot be wrong about
        which application it is describing. It settles quickly and is honest
        about being an estimate.
      */}
      {run.status === "running" && run.nodesTotal > 0 && (
        <div className="mb-2">
          <div className="h-1 overflow-hidden rounded bg-muted">
            <div
              className="h-full bg-primary transition-all duration-500"
              style={{
                width: `${Math.round((run.nodesDone / run.nodesTotal) * 100)}%`,
              }}
            />
          </div>
          <div className="mt-1 flex items-baseline justify-between text-xs text-muted-foreground">
            <span>
              {(() => {
                const busyNode = run.nodes.find((n) => n.state === "running");
                // A REATTACHED run has no node list — this client never saw
                // the stream that built one — so the stage name comes from the
                // server instead of falling back to "Thinking it through",
                // which is what an idle panel says.
                const verb = busyNode
                  ? STAGE_VERB[busyNode.key] ?? labelFor(busyNode.key)
                  : run.reattachedStage
                    ? STAGE_VERB[run.reattachedStage] ??
                      labelFor(run.reattachedStage)
                    : "Thinking it through";
                return busyNode?.subject
                  ? `${verb} · ${busyNode.subject}`
                  : verb;
              })()}
            </span>
            <span className="tabular-nums">
              {Math.round((run.nodesDone / run.nodesTotal) * 100)}%
              {started && ` · ${human(now - started)}`}
              {started && run.nodesDone > 0 &&
                run.nodesDone < run.nodesTotal &&
                ` · ~${human(
                  ((now - started) / run.nodesDone) *
                    (run.nodesTotal - run.nodesDone),
                )} left`}
            </span>
          </div>
        </div>
      )}

      {/* WHO IS DOING WHAT, RIGHT NOW. The bar above says how far; the
          office says what a build actually is — people working side by
          side, a reviewer sending pages back, a wait for the API. */}
      {(run.status === "running" || officeRunActive) && <OfficeStrip />}

      {/*
        ROUTES THAT WILL 404, SAID OUT LOUD. A page whose composition failed
        leaves no layout, so nothing is projected for it and the route falls
        through to the catch-all — while every node completed and the run
        reported success. /tickets was missing from a generated app for a day
        before anyone opened it.
      */}
      {run.unbuilt.length > 0 && (
        <div className="mb-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
          <p className="font-medium">
            {run.unbuilt.length} page
            {run.unbuilt.length === 1 ? "" : "s"} did not build
          </p>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {run.unbuilt.map((u, i) => (
              <li key={u.page ?? i}>{u.detail ?? u.page}</li>
            ))}
          </ul>
        </div>
      )}

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
    </div>
  );
}

/**
 * What Smith is working through, while it works through it.
 *
 * A turn that composes a screen runs for around a minute behind one `message`
 * event. Until that lands the panel shows a spinner, so a long turn and a
 * stuck one are indistinguishable — which is the same complaint as the empty
 * editor panels and the unreported runs: doing something and doing nothing
 * look identical from outside.
 *
 * SECONDARY BY CONSTRUCTION. Small, muted, and gone the moment Smith speaks —
 * the answer says it better than the reasoning that reached it. §111 asks that
 * BUILD PROGRESS show observable status rather than model reasoning, and the
 * stage list still does exactly that; this is the conversation, where the
 * reasoning is shown while it happens, labelled as thinking, never as a reply.
 */
export function ThinkingTrail({
  thoughts,
  nodes = [],
  busy,
}: {
  thoughts: RunThought[];
  nodes?: RunNode[];
  busy: boolean;
}) {
  // A live elapsed clock, so a turn that runs for minutes reads as working
  // rather than hung — the reassurance the stage list gives, in the chat. Runs
  // only while busy; resets the moment the turn ends.
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);
  useEffect(() => {
    if (!busy) {
      startRef.current = null;
      setElapsed(0);
      return;
    }
    startRef.current = Date.now();
    setElapsed(0);
    const id = setInterval(() => {
      if (startRef.current) setElapsed(Date.now() - startRef.current);
    }, 1000);
    return () => clearInterval(id);
  }, [busy]);

  // Deterministic `step` events are observable status — the compose stages,
  // labelled from the same table the build stage list uses.
  const steps = thoughts.filter((t) => t.kind === "step");
  const last = thoughts[thoughts.length - 1];

  // THE THINKING, SHOWN AS THINKING. The model's reasoning streams in as
  // fragments; joined, it is what Smith is weighing right now. It was hidden
  // after DEFECT-THINKING-LEAK, when a raw "Let me analyze this: 1. This is a
  // change request…" was painted into the chat AS IF IT WERE THE ANSWER. The
  // defect was the framing, not the content: rendered under its own
  // "Thinking" heading, muted and italic, scrolling, and gone the moment the
  // answer lands, it reads as what it is — the work in progress — and tells
  // the person what a twenty-second silence is about.
  // Each fragment is a whole thought — the server's ReasoningSink flushes at
  // sentence boundaries and trims what it flushes — so they go on their own
  // lines; joined flush, "…any visit." ran straight into "- REQ-004".
  const reasoning = thoughts
    .filter((t) => t.kind === "reasoning")
    .map((t) => t.text.trim())
    .filter(Boolean)
    .join("\n");
  const reasoningRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = reasoningRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [reasoning]);

  // Nothing happening and nothing to leave behind — render nothing.
  if (!busy && !steps.length) return null;

  // WHAT SMITH IS DOING, AS AN ACTION — a present participle, never a noun. The
  // running stage names it best ("Composing the screens"); failing that, the
  // last deterministic step; and when Smith is only reasoning, the honest word
  // is "Thinking". A "Thinking" header over "Generating the frontend" would
  // describe the wrong half of the turn.
  const running = nodes.find((n) => n.state === "running");
  const stepNode = last?.kind === "step" ? last.node : undefined;
  const activity =
    (running && (STAGE_VERB[running.key] ?? labelFor(running.key))) ||
    (stepNode && (STAGE_VERB[stepNode] ?? labelFor(stepNode))) ||
    "Thinking";

  return (
    <div className="max-w-[90%] space-y-1 border-l-2 border-muted pl-3">
      {busy && (
        <div className="flex items-center gap-2 whitespace-nowrap text-xs leading-none text-muted-foreground">
          {/* The Tentoro Forge loader — an anvil being struck. Its own
              animation is the working signal, so no spinner is needed; rendered
              only while busy, it stops the moment the turn ends. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/tentoro-forge-loader.gif"
            alt=""
            aria-hidden="true"
            className="h-9 w-9 shrink-0"
          />
          <span className="font-medium text-foreground">{activity}</span>
          <span aria-hidden="true">…</span>
          {elapsed >= 1000 && (
            <span className="tabular-nums text-muted-foreground/70">
              · {human(elapsed)}
            </span>
          )}
        </div>
      )}
      {steps.map((t, i) => (
        // Deterministic work, so it reads as status rather than thought —
        // upright, and labelled from the same table the stage list uses.
        <p key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Circle className="h-2 w-2 shrink-0 fill-current" />
          {t.node ? labelFor(t.node) : t.text}
        </p>
      ))}
      {busy && reasoning.trim() && (
        <div
          ref={reasoningRef}
          data-testid="smith-thinking"
          aria-label="Smith's thinking"
          className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md bg-muted/60 px-2.5 py-1.5 text-xs italic leading-relaxed text-muted-foreground"
        >
          {reasoning}
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
        : node.state === "failed"
          ? XCircle
          : Circle;

  return (
    <li className="flex items-center gap-2 text-xs">
      <Icon
        className={cn(
          "h-3.5 w-3.5 shrink-0",
          node.state === "done" && "text-green-600",
          node.state === "running" && "animate-spin text-primary",
          node.state === "failed" && "text-destructive",
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
