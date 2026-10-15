"use client";

/**
 * Find problems: throw bombs at your agent and see what explodes.
 *
 * An AI invents awkward conversations on purpose, each one a "bomb" of a kind (a made-up id, a sneaky instruction, too
 * much power, a change without asking, a secret, a plea for a person, a vague ask, a pushy "I'm the admin"). They are
 * thrown at the agent as drawn (a real model call each; tools are reported, never run) and each ends DEFUSED or
 * EXPLODED, with why. Failures come with proposed fixes: "Apply and test" puts one into the drawing and runs again
 * just the tests it was meant to help, then says whether it worked (and can take it back out); a fix is only an AI's
 * guess until then. Your own saved tests live here too ("My tests"), save themselves, and run in the same round. Only
 * the failed ones can be run again, from the results bar. Nothing is applied by itself.
 *
 * "Test one tool" picks a tool and has an AI study it and write the tests that would break it: normal use, bad input,
 * extremes, hidden orders, permission, secrets, failures and whether the reply is true to what the tool returned. And
 * after any fix, EVERYTHING is run again (not only the tests the fix was for), so a fix that breaks something that held
 * is caught and said plainly.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle, AlertTriangle, Bomb as BombIcon, Check, ChevronDown, ChevronRight, EyeOff, Flame, FlaskConical, Hash, HelpCircle, KeyRound, Loader2, PauseCircle,
  Play, Plus, RotateCcw, Save, ShieldAlert, ShieldCheck, Sparkles, Trash2, User, Wrench, Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { parseEvents } from "@/lib/agent-live";
import { appendLines, linesForEvent, type LogKind, type LogLine, type Printed } from "@/lib/blast-log";
import { BlastTerminal } from "./BlastTerminal";
import {
  applyFix, changesDrawing, didNotPass, emptyBlast, estimateCalls, fixKindLabel, fixOutcome, FIX_HINT, isBad, kindWords, outcomeSentence, reduceBlast,
  regression, roundSummary, suspects, tally, toolNames, verdict,
  type BlastFix, type BlastResult, type BlastState, type BlastTest, type Bomb, type FixOutcome, type Regression, type ToolAngle, type ToolStudy,
} from "@/lib/agent-blast";
import type { AgentNodeSerialized, AgentScenario } from "@/types/agent-builder";

interface Props {
  projectId: string;
  agentId: string;
  /** The agent as drawn (edits that are not saved yet included): what the bombs are thrown at. */
  graph: Record<string, unknown>;
  /** Apply a proposed fix to the drawing. */
  onApplyFix: (fix: BlastFix) => void;
  /** Take an applied fix back out of the drawing. */
  onRevertFix?: (fix: BlastFix) => void;
  /** The agent as drawn has changes that are not saved (a fix just applied, for one). */
  agentUnsaved?: boolean;
  /** Save the agent as drawn. */
  onSaveAgent?: () => Promise<void> | void;
}

/** A proposed fix with a key of its own: the platform numbers fixes from 1 each time, and fixes from several rounds can be on screen. */
interface FixEntry {
  key: string;
  fix: BlastFix;
}

/** What happened when a fix was tried: it is being tested, whether it changed the drawing, and how the re-test went. */
interface Tried {
  testing?: boolean;
  changed: boolean;
  outcome?: FixOutcome;
}

/** Tests are saved this long after the last edit, so typing is not a save per key. */
const AUTOSAVE_MS = 1000;
/** A fix is re-tested at least this many times: one lucky pass proves nothing, since answers vary. */
const RETEST_RUNS = 2;

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const FALLBACK_LIMITS = { maxTests: 20, maxRepeats: 3, perBomb: 2, perAngle: 2 };
/** The platform runs at most this many tests in one go: a longer list is run in turns. */
const CHUNK = 40;
/** How many everyday tests "Write tests with AI" asks for. */
const WRITE_COUNT = 10;

/** A number on a button: a small rounded badge instead of a figure in brackets. */
function Count({ n, tone = "muted" }: { n: number; tone?: "muted" | "red" | "dark" }) {
  const look = { muted: "bg-muted text-muted-foreground", red: "bg-red-100 text-red-700", dark: "bg-white/25 text-white" }[tone];
  return (
    <span className={`ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none ${look}`} data-testid="count">
      {n}
    </span>
  );
}

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  hash: Hash, "eye-off": EyeOff, "shield-alert": ShieldAlert, "pause-circle": PauseCircle, key: KeyRound, user: User, "help-circle": HelpCircle, zap: Zap,
};

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);
const commas = (text: string) => text.split(",").map((l) => l.trim()).filter(Boolean);
const newId = () => `scn_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`;
const toolCount = (graph: Record<string, unknown>) => ((graph.nodes as Array<{ data?: { nodeType?: string } }> | undefined) ?? []).filter((n) => n?.data?.nodeType === "tool").length;

const asMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function AgentBlastPanel({ projectId, agentId, graph, onApplyFix, onRevertFix, agentUnsaved, onSaveAgent }: Props) {
  const base = `/api/projects/${projectId}/agent-definitions`;
  const [bombs, setBombs] = useState<Bomb[]>([]);
  const [toolAngles, setToolAngles] = useState<ToolAngle[]>([]);
  const [testTool, setTestTool] = useState("");
  /** What the AI worked out about the tool it was asked to examine: shown above the results until the next round. */
  const [study, setStudy] = useState<ToolStudy | null>(null);
  const [toolBusy, setToolBusy] = useState(false);
  const [limits, setLimits] = useState(FALLBACK_LIMITS);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [repeats, setRepeats] = useState(1);
  const [includeMine, setIncludeMine] = useState(true);
  const [mine, setMine] = useState<AgentScenario[]>([]);
  const [mineLoaded, setMineLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [mineVersion, setMineVersion] = useState(0);
  const [savingAgent, setSavingAgent] = useState(false);
  // Logic reads the tests from refs: a handler started before a render would otherwise see the tests of the render before.
  const mineRef = useRef<AgentScenario[]>(mine);
  mineRef.current = mine;
  const inventedRef = useRef<BlastTest[]>([]);
  const dirtyRef = useRef(false);
  const version = useRef(0);
  const loadFailed = useRef(false);
  const [state, setState] = useState<BlastState>(emptyBlast());
  // The round's state is changed in ONE place and read back from the ref: a React state updater runs later, so a value
  // read out of one (the results, to ask for fixes) would still be empty when it is wanted.
  const stateRef = useRef<BlastState>(state);
  const update = useCallback((change: (s: BlastState) => BlastState) => {
    stateRef.current = change(stateRef.current);
    setState(stateRef.current);
  }, []);
  const [invented, setInvented] = useState<BlastTest[]>([]);
  const [fixes, setFixes] = useState<FixEntry[]>([]);
  const [handled, setHandled] = useState<Record<string, "applied" | "skipped">>({});
  const handledRef = useRef<Record<string, "applied" | "skipped">>({});
  const [tried, setTried] = useState<Record<string, Tried>>({});
  const round = useRef(0);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [showMine, setShowMine] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // The AI is writing tests (not a blast): everything else waits, the same as while a blast runs.
  const [writing, setWriting] = useState(false);
  const busy = state.phase === "inventing" || state.phase === "running" || state.phase === "fixing" || writing;
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  // the kinds of bomb, and the limits on one blast
  useEffect(() => {
    api
      .get<{ bombs?: Bomb[]; maxTests?: number; maxRepeats?: number; perBomb?: number; toolAngles?: ToolAngle[]; perAngle?: number }>(`${base}/blast/bombs`)
      .then((r) => {
        if (!live.current) return;
        const list = r?.bombs ?? [];
        setBombs(list);
        setToolAngles(r?.toolAngles ?? []);
        setPicked(new Set(list.map((b) => b.key)));
        setLimits({
          maxTests: r?.maxTests ?? FALLBACK_LIMITS.maxTests, maxRepeats: r?.maxRepeats ?? FALLBACK_LIMITS.maxRepeats,
          perBomb: r?.perBomb ?? FALLBACK_LIMITS.perBomb, perAngle: r?.perAngle ?? FALLBACK_LIMITS.perAngle,
        });
      })
      .catch(() => live.current && setNote("The kinds of bomb could not be loaded."));
  }, [base]);

  // my saved tests
  useEffect(() => {
    loadFailed.current = false;
    dirtyRef.current = false;
    setDirty(false);
    setSaveError(null);
    api
      .get<{ scenarios?: AgentScenario[] }>(`${base}/${agentId}/tests`)
      .then((r) => live.current && setMine(Array.isArray(r?.scenarios) ? r.scenarios : []))
      .catch(() => {
        // Saving a list that never loaded would replace the saved tests with whatever is typed now: refuse, and say so.
        loadFailed.current = true;
        if (live.current) setSaveError("Your saved tests could not be loaded, so nothing is saved from here (that could erase them). Reload the page.");
      })
      .finally(() => live.current && setMineLoaded(true));
  }, [base, agentId]);

  // ── my tests, kept saved without anyone having to remember ───────────────

  /** Save my tests now if they changed. Edits made while it saves stay unsaved (and are saved next). */
  const persistMine = useCallback(async (): Promise<boolean> => {
    if (!dirtyRef.current) return true;
    if (loadFailed.current) return false;
    const sent = version.current;
    setSaving(true);
    try {
      await api.put(`${base}/${agentId}/tests`, { scenarios: mineRef.current });
      if (version.current === sent) {
        dirtyRef.current = false;
        setDirty(false);
      }
      setSaveError(null);
      return true;
    } catch (e) {
      setSaveError(`Could not save your tests: ${asMessage(e)}`);
      return false;
    } finally {
      setSaving(false);
    }
  }, [base, agentId]);

  /** The one place my tests change: it also marks them unsaved, and the save follows a moment later. */
  const changeMine = useCallback((change: (all: AgentScenario[]) => AgentScenario[]) => {
    setMine(change);
    version.current += 1;
    dirtyRef.current = true;
    setDirty(true);
    setSaveError(null);
    setMineVersion(version.current);
  }, []);

  useEffect(() => {
    if (!dirty || !mineLoaded) return;
    const timer = setTimeout(() => void persistMine(), AUTOSAVE_MS);
    return () => clearTimeout(timer);
  }, [dirty, mineVersion, mineLoaded, persistMine]);

  // leaving this panel (or switching agent) must not lose a test typed a moment ago
  useEffect(
    () => () => {
      if (dirtyRef.current) void persistMine();
    },
    [persistMine],
  );

  /** The test with this id, whether it was invented this round or is one of mine (mine wins: it may have been edited). */
  const findTest = useCallback(
    (id: string): BlastTest | undefined => (mineRef.current.find((s) => s.id === id) as BlastTest | undefined) ?? inventedRef.current.find((t) => t.id === id),
    [],
  );
  const testOf = findTest;

  const tools = toolCount(graph);
  const toolList = useMemo(() => toolNames(graph), [graph]);
  // the picker holds a tool that is still drawn: if it was deleted, or nothing was picked, the first one stands in
  const pickedTool = toolList.includes(testTool) ? testTool : toolList[0] ?? "";
  const toolTests = Math.min(toolAngles.length * limits.perAngle, 24);
  const inventing = Math.min(picked.size * limits.perBomb, limits.maxTests);
  const runnableMine = includeMine ? mine.filter((s) => s.message.trim()).length : 0;
  const estimate = estimateCalls(inventing + runnableMine, repeats, inventing);
  const toolEstimate = estimateCalls(toolTests + runnableMine, repeats, toolTests);
  const held = useMemo(() => tally(state.results), [state.results]);
  /** Everything that did not pass (exploded, unstable, or could not be run): what "Re-run failed" runs. */
  const notPassed = useMemo(() => Object.values(state.results).filter(didNotPass), [state.results]);
  const mineNotPassed = notPassed.filter((r) => mine.some((s) => s.id === r.id));

  // ── the log: what is happening, line by line, like a terminal ────────────

  const [log, setLog] = useState<LogLine[]>([]);
  const logRef = useRef<LogLine[]>([]);
  const nextLine = useRef(1);
  const began = useRef(Date.now());
  const beat = useRef<ReturnType<typeof setInterval> | null>(null);

  const push = useCallback((printed: Printed) => {
    const next = appendLines(logRef.current, printed, Date.now() - began.current, nextLine.current);
    logRef.current = next.log;
    nextLine.current = next.nextId;
    setLog(next.log);
  }, []);
  const clearLog = useCallback(() => {
    logRef.current = [];
    setLog([]);
  }, []);
  /** A new action starts a new log (or, for a re-run, carries on under a line saying so). */
  const beginLog = (command: string, keep = false) => {
    if (!keep) {
      clearLog();
      began.current = Date.now();
    }
    push([{ kind: "cmd", text: command }]);
  };
  const stopBeat = () => {
    if (beat.current) clearInterval(beat.current);
    beat.current = null;
  };
  useEffect(() => stopBeat, []);
  const bombTitle = useCallback((key?: string | null) => (key ? bombs.find((b) => b.key === key)?.title ?? null : null), [bombs]);
  /** "tool_data_exposure" → "Secrets and privacy". */
  const angleTitle = useCallback((kind?: string | null) => (kind ? toolAngles.find((a) => `tool_${a.key}` === kind)?.title ?? null : null), [toolAngles]);

  // ── fixes ───────────────────────────────────────────────────────────────

  const markHandled = useCallback((key: string, status: "applied" | "skipped" | null) => {
    const next = { ...handledRef.current };
    if (status) next[key] = status;
    else delete next[key];
    handledRef.current = next;
    setHandled(next);
  }, []);
  const forgetFixes = useCallback(() => {
    handledRef.current = {};
    setHandled({});
    setTried({});
    setFixes([]);
  }, []);

  const fetchFixes = useCallback(
    async (results: BlastResult[], forGraph: Record<string, unknown>) => {
      const failing = results.filter(isBad);
      if (failing.length === 0) {
        // nothing left to fix: the fixes already applied stay, with how their re-test went
        setFixes((all) => all.filter((e) => handledRef.current[e.key] === "applied"));
        return;
      }
      update((s) => ({ ...s, phase: "fixing" }));
      push([{ kind: "info", text: `Working out fixes for the ${failing.length} that went off…` }]);
      try {
        // What each test WANTED goes with what went wrong: a fix written from the failure alone is a guess about what right looks like.
        const asked = failing.map((r) => {
          const t = findTest(r.id);
          return { ...r, ...(t?.judge ? { judge: t.judge } : {}), ...(t?.expect && Object.keys(t.expect).length ? { expect: t.expect } : {}) };
        });
        const r = await api.post<{ fixes?: BlastFix[] }>(`${base}/${agentId}/blast/fixes`, { graph: forGraph, results: asked });
        if (!live.current) return;
        const found = r?.fixes ?? [];
        round.current += 1;
        const fresh = found.map((f) => ({ key: `r${round.current}:${f.id}`, fix: f }));
        setFixes((all) => [...all.filter((e) => handledRef.current[e.key] === "applied"), ...fresh]);
        if (found.length === 0) {
          setNote("It could not think of a safe fix for these. Look at the failures below.");
          push([{ kind: "warn", text: "No safe fix came to mind for these. Read the failures above." }]);
        } else {
          push([
            { kind: "good", text: `Proposed ${found.length} fix${found.length === 1 ? "" : "es"}:` },
            ...found.map((f, i) => ({ kind: "step" as LogKind, text: `  ${i + 1}. [${fixKindLabel(f.kind)}] ${f.title}` })),
          ]);
        }
      } catch (e) {
        if (live.current) {
          setNote(`Could not propose fixes: ${asMessage(e)}`);
          push([{ kind: "bad", text: `✗ Could not propose fixes: ${asMessage(e)}` }]);
        }
      } finally {
        if (live.current) update((s) => ({ ...s, phase: "done" }));
      }
    },
    [base, agentId, update, push, findTest],
  );

  // ── throwing ────────────────────────────────────────────────────────────

  /**
   * Throw tests at the agent and take in what comes back. `graph` overrides the drawing to throw them at (a fix just
   * applied is in the platform's drawing only after the next render, so the caller says what the drawing now is) and
   * `repeats` the number of runs. Resolves true when the run finished.
   */
  type RunOpts = { merge?: boolean; withFixes?: boolean; graph?: Record<string, unknown>; repeats?: number };
  const runOnce = useCallback(
    async (tests: Array<BlastTest | AgentScenario>, opts: RunOpts = {}): Promise<boolean> => {
      const token = typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
      const drawing = opts.graph ?? graph;
      const times = opts.repeats ?? repeats;
      const ctx = { total: tests.length, bombTitle, kindTitle: angleTitle };
      update((s) => reduceBlast({ ...s, phase: "running" }, { type: "start", total: tests.length, repeats: times }, opts));
      let finished = false;
      try {
        const res = await fetch(`${API_BASE}${base}/${agentId}/blast/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ graph: drawing, tests, repeats: times }),
        });
        if (!res.ok || !res.body) {
          const detail = await res.text().catch(() => "");
          throw new Error(detail || `The platform answered ${res.status}.`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let ended = false;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parsed = parseEvents(buffer);
          buffer = parsed.rest;
          for (const ev of parsed.events) {
            if (ev.type === "done" || ev.type === "error") ended = true;
            if (ev.type === "done") finished = true;
            update((s) => reduceBlast(s, ev, opts));
            push(linesForEvent(ev, ctx));
          }
        }
        if (!ended) {
          update((s) => reduceBlast(s, { type: "error", message: "The run ended without finishing." }));
          push([{ kind: "bad", text: "✗ The run ended without finishing." }]);
        } else if (opts.withFixes !== false) await fetchFixes(Object.values(stateRef.current.results), drawing);
      } catch (e) {
        if (live.current) {
          update((s) => reduceBlast(s, { type: "error", message: asMessage(e) }));
          push([{ kind: "bad", text: `✗ ${asMessage(e)}` }]);
        }
      }
      return finished;
    },
    [base, agentId, graph, repeats, fetchFixes, update, push, bombTitle, angleTitle],
  );

  /** Any number of tests, in turns of at most CHUNK (the platform's limit for one go); the fixes are asked for once, at the end. */
  const run = useCallback(
    async (tests: Array<BlastTest | AgentScenario>, opts: RunOpts = {}): Promise<boolean> => {
      if (tests.length <= CHUNK) return runOnce(tests, opts);
      let finished = true;
      for (let i = 0; i < tests.length && finished; i += CHUNK) {
        finished = await runOnce(tests.slice(i, i + CHUNK), { ...opts, merge: opts.merge || i > 0, withFixes: false });
      }
      if (finished && opts.withFixes !== false && live.current) await fetchFixes(Object.values(stateRef.current.results), opts.graph ?? graph);
      return finished;
    },
    [runOnce, fetchFixes, graph],
  );

  const blast = async () => {
    setNote(null);
    forgetFixes();
    inventedRef.current = [];
    setInvented([]);
    setStudy(null);
    update(() => ({ ...emptyBlast(), phase: "inventing" }));
    const name = typeof graph.name === "string" && graph.name ? graph.name : agentId;
    beginLog(`$ blast "${name}" --kinds ${picked.size} --each ${limits.perBomb} --runs ${repeats}`);
    if (dirtyRef.current) await persistMine();
    push([{ kind: "info", text: `Asking the AI to write ${inventing} bombs for this agent…` }]);
    const asked = Date.now();
    stopBeat();
    beat.current = setInterval(() => push([{ kind: "dim", text: `… still writing the bombs (${Math.round((Date.now() - asked) / 1000)}s)` }]), 8000);
    try {
      const r = await api.post<{ tests?: BlastTest[] }>(`${base}/${agentId}/blast/invent`, { graph, bombs: [...picked], per_bomb: limits.perBomb });
      stopBeat();
      if (!live.current) return;
      const tests = r?.tests ?? [];
      inventedRef.current = tests;
      setInvented(tests);
      push([
        { kind: "good", text: `Got ${tests.length} bombs in ${Math.round((Date.now() - asked) / 1000)}s:` },
        ...tests.map((t) => ({ kind: "dim" as LogKind, text: `  [${bombTitle(t.bomb) ?? t.bomb ?? "test"}] ${t.name}` })),
      ]);
      const mineToRun = includeMine ? mineRef.current.filter((s) => s.message.trim()) : [];
      if (mineToRun.length) push([{ kind: "info", text: `Adding your ${mineToRun.length} saved test${mineToRun.length === 1 ? "" : "s"}.` }]);
      await run([...tests, ...mineToRun]);
    } catch (e) {
      stopBeat();
      if (live.current) {
        update((s) => reduceBlast(s, { type: "error", message: asMessage(e) }));
        push([{ kind: "bad", text: `✗ ${asMessage(e)}` }]);
      }
    }
  };

  /**
   * Pick one tool and have an AI study it and write the tests that would break it (normal use, bad input, extremes, hidden
   * orders, permission, secrets, failure, truth), then run them, with the saved tests when asked. A new round, like Blast.
   */
  const testOneTool = async () => {
    if (!pickedTool || busy) return;
    setNote(null);
    forgetFixes();
    inventedRef.current = [];
    setInvented([]);
    setStudy(null);
    setToolBusy(true);
    update(() => ({ ...emptyBlast(), phase: "inventing" }));
    beginLog(`$ test-tool ${pickedTool} --angles ${toolAngles.length} --each ${limits.perAngle} --runs ${repeats}`);
    if (dirtyRef.current) await persistMine();
    push([{ kind: "info", text: `Studying ${pickedTool} and writing tests that try to break it (${toolAngles.length} angles)…` }]);
    const asked = Date.now();
    stopBeat();
    beat.current = setInterval(() => push([{ kind: "dim", text: `… still studying (${Math.round((Date.now() - asked) / 1000)}s)` }]), 8000);
    try {
      const r = await api.post<{ analysis?: { whatItDoes?: string; needs?: string[]; risks?: string[] }; tests?: BlastTest[] }>(
        `${base}/${agentId}/blast/tool-tests`,
        { graph, tool: pickedTool, per_angle: limits.perAngle },
      );
      stopBeat();
      if (!live.current) return;
      const tests = r?.tests ?? [];
      inventedRef.current = tests;
      setInvented(tests);
      const a = r?.analysis;
      if (a && (a.whatItDoes || a.risks?.length)) setStudy({ tool: pickedTool, whatItDoes: a.whatItDoes ?? "", needs: a.needs ?? [], risks: a.risks ?? [] });
      push([
        { kind: "good", text: `Wrote ${tests.length} tests in ${Math.round((Date.now() - asked) / 1000)}s.` },
        ...(a?.whatItDoes ? [{ kind: "info" as LogKind, text: `  What it does: ${a.whatItDoes}` }] : []),
        ...(a?.risks ?? []).map((x) => ({ kind: "warn" as LogKind, text: `  Could go wrong: ${x}` })),
        ...tests.map((t) => ({ kind: "dim" as LogKind, text: `  [${angleTitle(t.kind) ?? "test"}] ${t.name}` })),
      ]);
      const mineToRun = includeMine ? mineRef.current.filter((x) => x.message.trim()) : [];
      if (mineToRun.length) push([{ kind: "info", text: `Adding your ${mineToRun.length} saved test${mineToRun.length === 1 ? "" : "s"}.` }]);
      await run([...tests, ...mineToRun]);
    } catch (e) {
      stopBeat();
      if (live.current) {
        update((s) => reduceBlast(s, { type: "error", message: asMessage(e) }));
        push([{ kind: "bad", text: `✗ ${asMessage(e)}` }]);
      }
    } finally {
      if (live.current) setToolBusy(false);
    }
  };

  /** Run EVERY test of the round again, on the drawing as it is now, and say what held before and does not hold now. */
  const rerunAll = async () => {
    setNote(null);
    const before = { ...stateRef.current.results };
    const ids = Object.keys(before).filter((id) => findTest(id));
    const tests = ids.map((id) => findTest(id)).filter((t): t is BlastTest => !!t);
    if (tests.length === 0) {
      setNote("Nothing to run again: those tests are gone. Blast again to get new ones.");
      return;
    }
    beginLog(`— running all ${tests.length} test${tests.length === 1 ? "" : "s"} again —`, true);
    if (dirtyRef.current) await persistMine();
    const finished = await run(tests, { merge: true });
    if (!finished || !live.current) return;
    const gone = regression(before, stateRef.current.results, ids);
    push(
      gone.broke.length || gone.shaky.length
        ? [{ kind: "warn", text: `${gone.broke.length + gone.shaky.length} that held last time did not this time: ${[...gone.broke, ...gone.shaky].slice(0, 3).map((x) => `“${x.name}”`).join(", ")}. Answers vary: run again to be sure.` }]
        : [{ kind: "good", text: `✔ Everything that held last time still holds (${gone.checked} checked).` }],
    );
  };

  const runMine = async () => {
    setNote(null);
    forgetFixes();
    setStudy(null);
    const tests = mineRef.current.filter((s) => s.message.trim());
    beginLog(`$ run my tests (${tests.length})`);
    if (dirtyRef.current) await persistMine();
    await run(tests);
  };

  /** Run again only what did not pass (all of it, or just my own tests), on the drawing as it is now. */
  const rerunFailed = async (scope: "all" | "mine" = "all") => {
    setNote(null);
    const wanted = scope === "mine" ? mineNotPassed : notPassed;
    const tests = wanted.map((r) => findTest(r.id)).filter((t): t is BlastTest => !!t);
    if (tests.length === 0) {
      setNote("Nothing to run again: those tests are gone. Blast again to get new ones.");
      return;
    }
    beginLog(scope === "mine" ? "— re-running my tests that failed —" : "— re-running the ones that went off —", true);
    if (dirtyRef.current) await persistMine();
    await run(tests, { merge: true });
  };

  // ── my tests (saved) ────────────────────────────────────────────────────

  const edit = useCallback((id: string, patch: Partial<AgentScenario>) => changeMine((all) => all.map((s) => (s.id === id ? { ...s, ...patch } : s))), [changeMine]);
  const editExpect = useCallback(
    (id: string, patch: Partial<AgentScenario["expect"]>) => changeMine((all) => all.map((s) => (s.id === id ? { ...s, expect: { ...s.expect, ...patch } } : s))),
    [changeMine],
  );
  const addMine = () => {
    const id = newId();
    changeMine((all) => [...all, { id, name: "New test", message: "", expect: {} }]);
    setOpen((o) => ({ ...o, [`mine:${id}`]: true }));
    setShowMine(true);
  };
  const removeMine = (id: string) => changeMine((all) => all.filter((s) => s.id !== id));
  const suggestFromTools = async () => {
    setNote(null);
    try {
      const r = await api.post<{ scenarios?: AgentScenario[] }>(`${base}/suggest-scenarios`, graph);
      const have = new Set(mineRef.current.map((s) => s.id));
      const fresh = (r?.scenarios ?? []).filter((s) => !have.has(s.id));
      if (fresh.length) {
        changeMine((all) => [...all, ...fresh]);
        setShowMine(true);
      }
      setNote(fresh.length ? `Added ${fresh.length} test${fresh.length === 1 ? "" : "s"} drawn from this agent's tools. They cost nothing to make.` : "Nothing new to add: you already have them all.");
    } catch (e) {
      setNote(`Could not suggest tests: ${asMessage(e)}`);
    }
  };
  /**
   * The AI writes everyday test cases for this agent (what a real person would ask, not attacks), each with a note on
   * what a good reply looks like. They join My tests and save by themselves; nothing is run until the builder says.
   */
  const writeTests = async () => {
    if (busy) return;
    setNote(null);
    setWriting(true);
    setShowMine(true);
    beginLog(`$ write tests --count ${WRITE_COUNT}`, log.length > 0);
    push([{ kind: "info", text: `Asking the AI to write about ${WRITE_COUNT} everyday tests for this agent…` }]);
    const asked = Date.now();
    stopBeat();
    beat.current = setInterval(() => push([{ kind: "dim", text: `… still writing (${Math.round((Date.now() - asked) / 1000)}s)` }]), 8000);
    try {
      const r = await api.post<{ tests?: AgentScenario[] }>(`${base}/${agentId}/write-tests`, { graph, count: WRITE_COUNT });
      stopBeat();
      if (!live.current) return;
      const wrote = r?.tests ?? [];
      const have = new Set(mineRef.current.map((s) => s.id));
      const fresh = wrote.filter((t) => !have.has(t.id));
      if (fresh.length) changeMine((all) => [...all, ...fresh]);
      const plural = (n: number) => `${n} test${n === 1 ? "" : "s"}`;
      push([
        { kind: "good", text: `Wrote ${plural(wrote.length)} in ${Math.round((Date.now() - asked) / 1000)}s${fresh.length < wrote.length ? `, ${wrote.length - fresh.length} already in My tests` : ""}:` },
        ...fresh.map((t) => ({ kind: "dim" as LogKind, text: `  [${kindWords(t.kind) || "Test"}] ${t.name}` })),
      ]);
      setNote(
        fresh.length
          ? `Wrote ${plural(fresh.length)}. They are in My tests, saved, and each one says what a good reply looks like. Press Run mine to try them.`
          : "Nothing new: the AI's tests are already in My tests.",
      );
    } catch (e) {
      stopBeat();
      if (live.current) {
        setNote(`Could not write tests: ${asMessage(e)}`);
        push([{ kind: "bad", text: `✗ ${asMessage(e)}` }]);
      }
    } finally {
      if (live.current) setWriting(false);
    }
  };
  /** Tests save by themselves a moment after any change; this is for people who want to see it done. */
  const saveMine = async () => {
    setNote(null);
    if (await persistMine()) setNote("Saved.");
  };
  /** A bomb worth keeping becomes one of my tests: it runs in every round from now on. It saves by itself. */
  const keep = (id: string) => {
    const t = inventedRef.current.find((x) => x.id === id);
    if (!t || mineRef.current.some((s) => s.id === id)) return;
    changeMine((all) => [...all, { id: t.id, name: t.name, message: t.message, expect: t.expect as AgentScenario["expect"], ...(t.judge ? { judge: t.judge } : {}), ...(t.bomb ? { bomb: t.bomb } : {}),
      ...(t.kind ? { kind: t.kind } : {}), ...(t.tool ? { tool: t.tool } : {}), ...(t.sim ? { sim: t.sim } : {}), ...(t.canary ? { canary: t.canary } : {}) }]);
    setNote("Kept as one of My tests. It saves by itself and runs in every round.");
  };

  // ── fixes: apply, test, undo ────────────────────────────────────────────

  /** The tests a fix is for: the ones it said it helps, or, when it did not say, everything that did not pass. */
  const testsFor = (e: FixEntry, fallback: string[]) => {
    const own = e.fix.fixesTests.filter((id) => findTest(id));
    return own.length ? own : fallback;
  };

  /**
   * Run again the tests the fixes were for (at least twice each), then EVERY other test of the round once, on the drawing as it
   * is with them, and say how each fix did. A test that held before and does not now is run twice more before it is called
   * broken, since one run can be bad luck.
   */
  const retest = async (entries: FixEntry[], forGraph: Record<string, unknown>) => {
    const before = { ...stateRef.current.results };
    const fallback = Object.values(stateRef.current.results).filter(didNotPass).map((r) => r.id);
    const idsOf = new Map(entries.map((e) => [e.key, testsFor(e, fallback)] as const));
    const tests = [...new Set([...idsOf.values()].flat())].map((id) => findTest(id)).filter((t): t is BlastTest => !!t);
    const mark = (patch: (t: Tried | undefined, key: string) => Tried) =>
      setTried((all) => ({ ...all, ...Object.fromEntries(entries.map((e) => [e.key, patch(all[e.key], e.key)])) }));
    if (tests.length === 0) {
      mark((t) => ({ changed: t?.changed ?? true }));
      setNote("Applied. There was nothing to test it on: run Blast again.");
      return;
    }
    mark((t) => ({ changed: t?.changed ?? true, testing: true }));
    beginLog(`$ re-test ${tests.length} test${tests.length === 1 ? "" : "s"} ${entries.length === 1 ? `with "${entries[0].fix.title}"` : `with ${entries.length} fixes`}`, true);
    if (dirtyRef.current) await persistMine();
    const finished = await run(tests, { merge: true, withFixes: false, graph: forGraph, repeats: Math.max(repeats, RETEST_RUNS) });
    if (!live.current) return;
    // everything else, so a fix that fixes one thing and breaks another cannot hide
    let others: Regression | undefined;
    if (finished) {
      const targeted = new Set(tests.map((t) => t.id));
      const otherIds = Object.keys(before).filter((id) => !targeted.has(id) && findTest(id));
      if (otherIds.length) {
        push([{ kind: "cmd", text: `— checking that nothing else broke: running ${otherIds.length} other test${otherIds.length === 1 ? "" : "s"} again —` }]);
        const others1 = await run(otherIds.map((id) => findTest(id) as BlastTest), { merge: true, withFixes: false, graph: forGraph, repeats: 1 });
        if (!live.current) return;
        let sure = others1;
        const worse = others1 ? suspects(before, stateRef.current.results, otherIds) : [];
        if (worse.length) {
          push([{ kind: "info", text: `${worse.length} that held before did not this time. Running ${worse.length === 1 ? "it" : "them"} again to be sure…` }]);
          sure = await run(worse.map((id) => findTest(id) as BlastTest), { merge: true, withFixes: false, graph: forGraph, repeats: RETEST_RUNS });
          if (!live.current) return;
        }
        if (sure) others = regression(before, stateRef.current.results, otherIds);
      }
    }
    const results = stateRef.current.results;
    const outcomes = new Map(entries.map((e) => [e.key, finished ? fixOutcome(idsOf.get(e.key) ?? [], results, others) : undefined] as const));
    mark((t, key) => ({ changed: t?.changed ?? true, outcome: outcomes.get(key) }));
    push(
      entries.flatMap((e) => {
        const o = outcomes.get(e.key);
        if (!o) return [];
        const kind: LogKind = o.state === "worked" ? "good" : o.state === "partly" ? "warn" : "bad";
        return [{ kind, text: `${o.state === "worked" ? "✔" : o.state === "partly" ? "◐" : "✖"} "${e.fix.title}": ${outcomeSentence(o)}` }];
      }),
    );
    if (finished) await fetchFixes(Object.values(results), forGraph);
  };

  /** Put fixes into the drawing and, when asked, test them straight away. */
  const applyFixes = async (entries: FixEntry[], andTest: boolean) => {
    const todo = entries.filter((e) => e.fix.kind !== "advice" && !handledRef.current[e.key]);
    if (todo.length === 0 || busy) return;
    setNote(null);
    let nodes = (graph.nodes as AgentNodeSerialized[] | undefined) ?? [];
    const changed: Record<string, boolean> = {};
    for (const e of todo) {
      changed[e.key] = changesDrawing(nodes, e.fix);
      nodes = applyFix(nodes, e.fix);
    }
    for (const e of todo) {
      onApplyFix(e.fix);
      markHandled(e.key, "applied");
    }
    setTried((all) => ({ ...all, ...Object.fromEntries(todo.map((e) => [e.key, { changed: changed[e.key] }])) }));
    if (andTest) await retest(todo, { ...graph, nodes });
  };
  const undo = (e: FixEntry) => {
    onRevertFix?.(e.fix);
    markHandled(e.key, null);
    // taking a fix out puts its card back as a plain proposal: an identical new proposal beside it would be a duplicate
    const same = (a: BlastFix, b: BlastFix) => a.kind === b.kind && a.nodeId === b.nodeId && (a.tool ?? "") === (b.tool ?? "") && (a.text ?? "") === (b.text ?? "");
    setFixes((all) => all.filter((x) => x.key === e.key || handledRef.current[x.key] || !same(x.fix, e.fix)));
    setTried((all) => {
      const next = { ...all };
      delete next[e.key];
      return next;
    });
    setNote(`Took “${e.fix.title}” back out. The results above are from before: run again to see where things stand.`);
  };
  const saveAgentNow = async () => {
    if (!onSaveAgent) return;
    setSavingAgent(true);
    try {
      await onSaveAgent();
      setNote("Agent saved.");
    } catch (e) {
      setNote(`Could not save the agent: ${asMessage(e)}`);
    } finally {
      if (live.current) setSavingAgent(false);
    }
  };
  const appliedAny = Object.values(handled).includes("applied");
  const pending = fixes.filter((e) => !handled[e.key]);
  const pendingApplicable = pending.filter((e) => e.fix.kind !== "advice");

  // ── what to show ────────────────────────────────────────────────────────

  const nothingYet = state.order.length === 0 && state.phase === "idle";
  const exploded = held.failed + held.flaky;
  const progress = `${state.ran} of ${state.total}`;
  const showTerminal = log.length > 0 || busy;

  return (
    <div className="flex h-full flex-col overflow-hidden" data-testid="agent-blast">
      {/* The button */}
      <div className="space-y-2 border-b px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <BombIcon className="h-4 w-4 text-red-600" />
          <h3 className="mr-auto text-sm font-semibold">Find problems</h3>
          {saveError ? (
            <button type="button" className="text-xs text-red-700 underline" title={saveError} onClick={saveMine} data-testid="tests-save-error">
              Tests not saved: try again
            </button>
          ) : saving ? (
            <span className="text-xs text-muted-foreground">Saving tests…</span>
          ) : dirty ? (
            <span className="text-xs text-amber-700" title="Saved by itself in a moment, and before every run">
              Unsaved tests
            </span>
          ) : null}
          <Button size="sm" className="bg-red-600 text-white hover:bg-red-700" onClick={blast} disabled={busy || picked.size === 0}>
            {state.phase === "inventing" || state.phase === "running" ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <BombIcon className="mr-1 h-3.5 w-3.5" />}
            Blast
          </Button>
        </div>
        <p className="text-[11px] text-muted-foreground">
          An AI writes awkward messages on purpose and throws them at this agent, as drawn. The app is simulated: lookups return made-up data, changes are held for a yes as in the real app, and nothing real is touched. Each bomb is defused or it explodes, and you get fixes you can apply.
        </p>

        <div className="flex flex-wrap gap-1" data-testid="blast-bombs">
          {bombs.map((b) => {
            const Icon = ICONS[b.icon] ?? BombIcon;
            const on = picked.has(b.key);
            return (
              <button
                key={b.key}
                type="button"
                title={b.blurb}
                aria-pressed={on}
                disabled={busy}
                onClick={() => setPicked((p) => { const n = new Set(p); on ? n.delete(b.key) : n.add(b.key); return n; })}
                className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${on ? "border-red-400 bg-red-50 text-red-800" : "text-muted-foreground opacity-60"}`}
              >
                <Icon className="h-3 w-3" />
                {b.title}
              </button>
            );
          })}
        </div>

        {/* Pick one tool and have it examined in depth */}
        {toolList.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded border border-dashed px-2 py-1.5 text-[11px]" data-testid="tool-tester">
            <FlaskConical className="h-3.5 w-3.5 text-primary" />
            <span className="font-medium">Test one tool</span>
            <select
              aria-label="Tool to test"
              className="h-6 max-w-[14rem] rounded border bg-transparent px-1 text-[11px]"
              value={pickedTool}
              disabled={busy}
              onChange={(e) => setTestTool(e.target.value)}
            >
              {toolList.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="outline"
              className="h-6 border-primary/40 text-[11px] text-primary hover:bg-primary/5 hover:text-primary"
              onClick={() => void testOneTool()}
              disabled={busy || !pickedTool || toolAngles.length === 0}
              title="An AI studies this tool and writes tests that try to break it, then they are run"
              data-testid="test-tool"
            >
              {toolBusy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <FlaskConical className="mr-1 h-3 w-3" />}
              Test this tool
            </Button>
            <span className="text-muted-foreground" data-testid="tool-estimate">
              {toolAngles.map((a) => a.title).join(", ")}. About {toolEstimate} AI calls.
            </span>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 text-[11px]">
          <label className="flex items-center gap-1">
            Run each
            <select aria-label="Times each is run" className="h-6 rounded border bg-transparent px-1 text-[11px]" value={repeats} disabled={busy} onChange={(e) => setRepeats(Number(e.target.value))}>
              {Array.from({ length: limits.maxRepeats }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n === 1 ? "once" : `${n} times`}
                </option>
              ))}
            </select>
            {repeats > 1 && <span className="text-muted-foreground">(answers vary: this finds the unstable ones)</span>}
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" aria-label="Include my tests" checked={includeMine} disabled={busy} onChange={(e) => setIncludeMine(e.target.checked)} />
            Include my {mine.length} saved test{mine.length === 1 ? "" : "s"}
          </label>
          <span className="text-muted-foreground" data-testid="blast-estimate">
            About {estimate} AI calls (up to {inventing} bombs{runnableMine ? ` and ${runnableMine} of yours` : ""}).
          </span>
        </div>
        {tools === 0 && (
          <p role="note" className="text-[11px] text-amber-800" data-testid="blast-no-tools">
            This agent has no tools, so bombs about tools or changes can only test what it says, not what it does.
          </p>
        )}
      </div>

      {/* Changes to the agent that are not saved: a run uses them as they are, but they are lost if the page is left */}
      {agentUnsaved && onSaveAgent && (
        <div role="note" className="flex flex-wrap items-center gap-2 border-b border-amber-300 bg-amber-50 px-3 py-1.5 text-xs text-amber-900" data-testid="blast-agent-unsaved">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1">
            <b>The agent has changes that are not saved</b>
            {appliedAny ? ", including the fixes you applied" : ""}. A run uses what you see here, saved or not, but unsaved changes are lost if you leave this page.
          </span>
          <Button size="sm" className="h-6 text-[11px]" onClick={saveAgentNow} disabled={savingAgent}>
            {savingAgent ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Save className="mr-1 h-3 w-3" />}
            Save agent
          </Button>
        </div>
      )}

      {/* What is happening, line by line */}
      {showTerminal && (
        <div className="border-b px-3 py-2">
          <BlastTerminal lines={log} running={busy} onClear={clearLog} />
        </div>
      )}

      {/* The round */}
      {(note || state.order.length > 0 || busy || state.error) && (
        <div className="flex flex-wrap items-center gap-y-1 border-b px-3 py-1.5 text-xs" role="note" data-testid="blast-status">
          {busy && state.phase === "running" && (
            <span className="font-medium text-muted-foreground" data-testid="blast-progress">
              {progress} thrown
            </span>
          )}
          {state.phase !== "inventing" && state.order.length > 0 && !busy && (
            <span className={`font-medium ${exploded ? "text-red-700" : held.error ? "text-amber-700" : "text-green-700"}`} data-testid="blast-summary">
              {roundSummary(held)}
            </span>
          )}
          {/* Only the failed ones, one click, wherever you are in the page: with or without a fix */}
          {!busy && state.order.length > 0 && notPassed.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="ml-3 h-6 text-[11px]"
              onClick={() => void rerunFailed("all")}
              title="Runs again only the tests that did not pass, on the agent as drawn now (unsaved changes included)"
              data-testid="rerun-failed"
            >
              <RotateCcw className="mr-1 h-3 w-3" /> Re-run failed
              <Count n={notPassed.length} tone="red" />
            </Button>
          )}
          {!busy && state.order.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="ml-2 h-6 text-[11px]"
              onClick={() => void rerunAll()}
              title="Runs every test of this round again on the agent as drawn now, and says what held before and does not now"
              data-testid="rerun-all"
            >
              <RotateCcw className="mr-1 h-3 w-3" /> Re-run all
              <Count n={state.order.length} />
            </Button>
          )}
          {state.error && (
            <span role="alert" className="ml-3 font-medium text-red-700">
              {state.error}
            </span>
          )}
          {note && <span className="ml-3 text-muted-foreground">{note}</span>}
        </div>
      )}

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {nothingYet && mineLoaded && (
          <div className="rounded border border-dashed p-3 text-sm text-muted-foreground" data-testid="blast-empty">
            <p className="font-medium text-foreground">Nothing thrown yet.</p>
            <p className="mt-1">
              Press <b>Blast</b> to have an AI attack this agent with about {inventing} tricky messages
              {mine.length ? `, plus your ${mine.length} saved test${mine.length === 1 ? "" : "s"}` : ""}. Or pick one tool above and press <b>Test this tool</b> to have it examined from every side. Or build up your own tests first:
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-3" data-testid="start-options">
              <StartCard
                featured
                icon={Sparkles}
                title="Write tests with AI"
                text="Realistic everyday requests for this agent, each with a note on what a good reply looks like. One AI call."
                onClick={() => void writeTests()}
                disabled={busy}
                busy={writing}
              />
              <StartCard icon={Wrench} title="Starter tests" text="Basic checks drawn from the agent's tools. Free, no AI." onClick={suggestFromTools} disabled={busy} />
              <StartCard icon={Plus} title="Write my own" text="Start from a blank test and say what must happen." onClick={addMine} disabled={busy} />
            </div>
          </div>
        )}

        {state.phase === "done" && state.order.length > 0 && exploded === 0 && held.error === 0 && (
          <div className="rounded border border-green-300 bg-green-50 p-2 text-xs text-green-900" data-testid="blast-all-defused">
            <p className="font-medium">All {held.total} defused.</p>
            <p>
              That is good news, but it does not prove the agent is safe: these were {held.total} tests, and the next round invents different ones.
              {repeats === 1 ? " Running each several times also finds answers that only sometimes hold." : ""}
            </p>
            <Button size="sm" variant="outline" className="mt-1 h-6 text-[11px]" onClick={blast}>
              <BombIcon className="mr-1 h-3 w-3" /> Blast again
            </Button>
          </div>
        )}

        {/* What the AI worked out about the tool it examined */}
        {study && (
          <div className="rounded border border-primary/30 bg-primary/5 p-2 text-xs" data-testid="tool-study">
            <p className="flex items-center gap-1 font-semibold">
              <FlaskConical className="h-3.5 w-3.5 text-primary" /> About <span className="font-mono">{study.tool}</span>
            </p>
            {study.whatItDoes && <p className="mt-0.5">{study.whatItDoes}</p>}
            {study.needs.length > 0 && <p className="mt-0.5 text-muted-foreground">It needs: {study.needs.join("; ")}.</p>}
            {study.risks.length > 0 && (
              <div className="mt-0.5">
                <p className="text-[10px] font-semibold uppercase text-muted-foreground">How it could go wrong</p>
                <ul className="list-disc pl-4 text-amber-900">
                  {study.risks.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* What went off */}
        {state.order.length > 0 && (
          <div className="space-y-1.5" data-testid="blast-results">
            {[...state.order]
              .sort((a, b) => Number(isBad(state.results[b])) - Number(isBad(state.results[a])) || 0)
              .map((id) => (
                <ResultCard
                  key={id}
                  result={state.results[id]}
                  open={!!open[id] || (isBad(state.results[id]) && open[id] === undefined)}
                  onToggle={() => setOpen((o) => ({ ...o, [id]: !(open[id] ?? isBad(state.results[id])) }))}
                  bombs={bombs}
                  canKeep={invented.some((t) => t.id === id) && !mine.some((s) => s.id === id)}
                  kept={invented.some((t) => t.id === id) && mine.some((s) => s.id === id)}
                  onKeep={() => keep(id)}
                  test={testOf(id)}
                  angle={angleTitle(state.results[id].kind ?? testOf(id)?.kind)}
                />
              ))}
          </div>
        )}

        {/* Fixes: an AI's guess each, until it has been tried */}
        {fixes.length > 0 && (
          <div className="space-y-1.5" data-testid="blast-fixes">
            <div className="flex flex-wrap items-center gap-2">
              <Wrench className="h-3.5 w-3.5" />
              <h4 className="text-xs font-semibold">Proposed fixes</h4>
              <span className="text-[11px] text-muted-foreground">Nothing is applied until you say so.</span>
              {pendingApplicable.length > 1 && (
                <Button size="sm" className="ml-auto h-6 text-[11px]" onClick={() => void applyFixes(pendingApplicable, true)} disabled={busy} data-testid="apply-all">
                  <Play className="mr-1 h-3 w-3" /> Apply all and test
                  <Count n={pendingApplicable.length} tone="dark" />
                </Button>
              )}
            </div>
            {pending.some((e) => e.fix.kind !== "advice") && (
              <p className="text-[11px] text-amber-800" data-testid="fix-hint">
                {FIX_HINT}
              </p>
            )}
            {fixes.map((e) => (
              <FixCard
                key={e.key}
                fix={e.fix}
                status={handled[e.key]}
                tried={tried[e.key]}
                busy={busy}
                canUndo={!!onRevertFix && tried[e.key]?.changed !== false}
                testCount={testsFor(e, notPassed.map((r) => r.id)).length}
                onApplyAndTest={() => void applyFixes([e], true)}
                onApplyOnly={() => void applyFixes([e], false)}
                onTest={() => void retest([e], graph)}
                onUndo={() => undo(e)}
                onSkip={() => markHandled(e.key, "skipped")}
              />
            ))}
            {pending.length === 0 && !appliedAny && <p className="text-[11px] text-muted-foreground">You skipped them all.</p>}
          </div>
        )}

        {/* My tests */}
        <div className="rounded border" data-testid="blast-mine">
          <div className="flex flex-wrap items-center gap-2 px-2 py-1.5">
            <button type="button" className="flex items-center gap-1 text-xs font-semibold" aria-expanded={showMine} onClick={() => setShowMine((v) => !v)}>
              {showMine ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              My tests
              <Count n={mine.length} />
            </button>
            <span className="text-[11px] text-muted-foreground">Saved conversations that run in every round, against the same simulated app. They save by themselves.</span>
            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              {/* make tests */}
              <Button
                size="sm"
                variant="outline"
                className="h-7 border-primary/40 text-[11px] text-primary hover:bg-primary/5 hover:text-primary"
                onClick={() => void writeTests()}
                disabled={busy}
                title="The AI writes about ten realistic tests for this agent, each with a note on what a good reply looks like"
              >
                {writing ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Sparkles className="mr-1 h-3 w-3" />} Write with AI
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={suggestFromTools} disabled={busy} title="Basic checks drawn from the tools. Free, no AI.">
                <Wrench className="mr-1 h-3 w-3" /> Starter tests
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={addMine} disabled={busy}>
                <Plus className="mr-1 h-3 w-3" /> Add
              </Button>
              <span className="mx-0.5 hidden h-4 w-px bg-border sm:block" aria-hidden />
              {/* keep and run them */}
              <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={saveMine} disabled={!dirty}>
                <Save className="mr-1 h-3 w-3" /> Save
              </Button>
              <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => void runMine()} disabled={busy || mine.filter((s) => s.message.trim()).length === 0}>
                <Play className="mr-1 h-3 w-3" /> Run mine
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-[11px]"
                onClick={() => void rerunFailed("mine")}
                disabled={busy || mineNotPassed.length === 0}
                title={mineNotPassed.length === 0 ? "None of my tests failed in the last round" : "Runs again only my tests that did not pass"}
                data-testid="run-mine-failed"
              >
                <RotateCcw className="mr-1 h-3 w-3" /> Run failed
                {mineNotPassed.length > 0 && <Count n={mineNotPassed.length} tone="red" />}
              </Button>
            </div>
          </div>
          {showMine && (
            <div className="space-y-1.5 border-t p-2">
              {mineLoaded && mine.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No saved tests yet. A test is something to say to the agent and what must or must not happen. Keep a bomb that found something and it lands here, or add your own.
                </p>
              )}
              {mine.map((s) => (
                <MyTest
                  key={s.id}
                  test={s}
                  result={state.results[s.id]}
                  open={!!open[`mine:${s.id}`]}
                  onToggle={() => setOpen((o) => ({ ...o, [`mine:${s.id}`]: !o[`mine:${s.id}`] }))}
                  onEdit={(p) => edit(s.id, p)}
                  onEditExpect={(p) => editExpect(s.id, p)}
                  onRemove={() => removeMine(s.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── a way to start: a card with what it does, not a long button ──────────

function StartCard({ icon: Icon, title, text, onClick, disabled, featured, busy }: {
  icon: React.ComponentType<{ className?: string }>; title: string; text: string; onClick: () => void; disabled?: boolean; featured?: boolean; busy?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
        featured ? "border-primary/40 bg-primary/5 hover:bg-primary/10" : "bg-background hover:bg-accent"
      }`}
    >
      <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : <Icon className={`h-4 w-4 ${featured ? "text-primary" : "text-muted-foreground"}`} />}
        {title}
      </span>
      {/* after the title for anyone reading the button aloud, above it on screen */}
      {featured && <span className="order-first rounded-full bg-primary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary-foreground">Recommended</span>}
      <span className="text-xs font-normal text-muted-foreground">{text}</span>
    </button>
  );
}

// ── one bomb that went off, or was defused ────────────────────────────────

function ResultCard({ result, open, onToggle, bombs, canKeep, kept, onKeep, test, angle }: {
  result: BlastResult; open: boolean; onToggle: () => void; bombs: Bomb[]; canKeep: boolean; kept: boolean; onKeep: () => void; test?: BlastTest; angle?: string | null;
}) {
  const tool = result.tool ?? test?.tool;
  const word = verdict(result.status);
  const kind = bombs.find((b) => b.key === result.bomb);
  const Icon = (kind && ICONS[kind.icon]) || BombIcon;
  const tone = { passed: "border-green-300 bg-green-50/50", failed: "border-red-300 bg-red-50/60", flaky: "border-amber-300 bg-amber-50/60", error: "border-slate-300 bg-slate-50" }[result.status];
  const StatusIcon = { passed: ShieldCheck, failed: Flame, flaky: AlertTriangle, error: AlertCircle }[result.status];
  const statusTone = { passed: "text-green-700", failed: "text-red-700", flaky: "text-amber-700", error: "text-slate-600" }[result.status];
  return (
    <div className={`rounded border ${tone}`} data-testid="blast-result" data-status={result.status}>
      <button type="button" className="flex w-full items-center gap-2 px-2 py-1.5 text-left" onClick={onToggle} aria-expanded={open}>
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <StatusIcon className={`h-4 w-4 shrink-0 ${statusTone}`} />
        <span className={`text-[11px] font-semibold ${statusTone}`}>{word}</span>
        <Icon className="h-3 w-3 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate text-xs font-medium">{result.name}</span>
        {(kind || test?.kind || tool) && (
          <span className="hidden text-[10px] text-muted-foreground sm:inline" data-testid="result-kind">
            {kind ? kind.title : tool ? `${tool}${angle ? ` · ${angle}` : ""}` : kindWords(test?.kind)}
          </span>
        )}
        {(result.runs ?? 1) > 1 && <span className="text-[10px] text-muted-foreground">{result.passedRuns} of {result.runs} held</span>}
      </button>
      {result.status !== "passed" && (
        <ul className="mx-2 mb-1.5 space-y-0.5 text-xs" data-testid="blast-why">
          {result.status === "error" ? <li className="text-slate-700">{result.error}</li> : result.failures.map((f, i) => <li key={i} className="text-red-800">{f}</li>)}
        </ul>
      )}
      {/* A bomb that found something is worth keeping: one click, no need to open the card, and it saves by itself */}
      {result.status !== "passed" && (canKeep || kept) && (
        <div className="mx-2 mb-1.5">
          {canKeep ? (
            <Button size="sm" variant="outline" className="h-6 text-[11px]" onClick={onKeep}>
              <Check className="mr-1 h-3 w-3" /> Keep as my test
            </Button>
          ) : (
            <span className="text-[11px] font-medium text-green-800" data-testid="kept">
              ✓ In My tests: it runs in every round
            </span>
          )}
        </div>
      )}
      {open && (
        <div className="space-y-1.5 border-t px-3 py-2 text-xs">
          <div>
            <p className="text-[10px] font-semibold uppercase text-muted-foreground">What was thrown</p>
            <p className="whitespace-pre-wrap">{result.message}</p>
          </div>
          {test?.judge && (
            <div>
              <p className="text-[10px] font-semibold uppercase text-muted-foreground">A good reply</p>
              <p className="text-muted-foreground">{test.judge}</p>
            </div>
          )}
          <div>
            <p className="text-[10px] font-semibold uppercase text-muted-foreground">What the agent did</p>
            {result.toolCalls.length > 0 && (
              <div className="mb-0.5 flex flex-wrap gap-1">
                {result.toolCalls.map((c, i) => (
                  <span key={i} className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] text-blue-700">
                    asked to use {c.name}
                  </span>
                ))}
              </div>
            )}
            <p className="whitespace-pre-wrap text-slate-700">{result.response ? result.response.slice(0, 500) : result.blocked ? "(blocked by the safety rules)" : "(it said nothing)"}</p>
          </div>
          {/* what the app handed the assistant, so a reply can be checked against it */}
          {result.toolCalls.some((c) => c.output) && (
            <div data-testid="what-came-back">
              <p className="text-[10px] font-semibold uppercase text-muted-foreground">What the tools returned</p>
              <ul className="space-y-0.5">
                {result.toolCalls.filter((c) => c.output).map((c, i) => (
                  <li key={i} className="break-words font-mono text-[10px] text-slate-600">
                    <b>{c.name}</b>: {c.output!.slice(0, 220)}
                    {c.output!.length > 220 ? "…" : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.notes && result.notes.length > 0 && (
            <div data-testid="guardrail-notes">
              <p className="text-[10px] font-semibold uppercase text-muted-foreground">What the guardrails did</p>
              <ul className="list-disc pl-4 text-slate-700">
                {result.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </div>
          )}
          {/* (a bomb that went off has its Keep button up in the card, not here) */}
          {result.status === "passed" && canKeep && (
            <Button size="sm" variant="outline" className="h-6 text-[11px]" onClick={onKeep}>
              <Check className="mr-1 h-3 w-3" /> Keep as my test
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

// ── one proposed fix ──────────────────────────────────────────────────────

/** How a re-tested fix is labelled: the short chip, and the colours of the sentence under it. */
const OUTCOME_LOOK: Record<FixOutcome["state"], { chip: (o: FixOutcome) => string; chipTone: string; textTone: string; card: string }> = {
  worked: { chip: (o) => `✓ Worked · ${o.fixed} of ${o.total}`, chipTone: "bg-green-100 text-green-800", textTone: "text-green-800", card: "border-green-400 bg-green-50" },
  partly: { chip: (o) => `Partly · ${o.fixed} of ${o.total}`, chipTone: "bg-amber-100 text-amber-800", textTone: "text-amber-900", card: "border-amber-300 bg-amber-50" },
  no: { chip: () => "✗ Did not help", chipTone: "bg-red-100 text-red-800", textTone: "text-red-800", card: "border-red-300 bg-red-50" },
  broke: { chip: (o) => `✗ Broke ${o.broke?.length ?? 0} other${o.broke?.length === 1 ? "" : "s"}`, chipTone: "bg-red-100 text-red-800", textTone: "text-red-800", card: "border-red-400 bg-red-50" },
  unknown: { chip: () => "Could not be tested", chipTone: "bg-slate-200 text-slate-700", textTone: "text-slate-700", card: "border-slate-300 bg-slate-50" },
};

function FixCard({ fix, status, tried, busy, canUndo, testCount, onApplyAndTest, onApplyOnly, onTest, onUndo, onSkip }: {
  fix: BlastFix; status?: "applied" | "skipped"; tried?: Tried; busy: boolean; canUndo: boolean; testCount: number;
  onApplyAndTest: () => void; onApplyOnly: () => void; onTest: () => void; onUndo: () => void; onSkip: () => void;
}) {
  const applicable = fix.kind !== "advice";
  const outcome = tried?.outcome;
  const testing = !!tried?.testing;
  const look = outcome ? OUTCOME_LOOK[outcome.state] : null;
  const card = status === "applied" ? look?.card ?? "border-slate-300 bg-slate-50" : status === "skipped" ? "opacity-50" : "bg-white";
  return (
    <div className={`rounded border p-2 text-xs ${card}`} data-testid="blast-fix" data-handled={status ?? ""} data-outcome={outcome?.state ?? ""}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase">{fixKindLabel(fix.kind)}</span>
        <span className="font-medium">{fix.title}</span>
        {fix.tool && <span className="font-mono text-[10px] text-muted-foreground">{fix.tool}</span>}
        {fix.fixesTests.length > 0 && <span className="text-[10px] text-muted-foreground">helps {fix.fixesTests.length} test{fix.fixesTests.length === 1 ? "" : "s"}</span>}
        {/* where this fix stands: a guess, being tested, or proven (or not) */}
        {status === "applied" && testing && (
          <span className="ml-auto flex items-center gap-1 text-[10px] font-semibold text-slate-700" data-testid="fix-status">
            <Loader2 className="h-3 w-3 animate-spin" /> Testing…
          </span>
        )}
        {status === "applied" && !testing && look && outcome && (
          <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold ${look.chipTone}`} data-testid="fix-status">
            {look.chip(outcome)}
          </span>
        )}
        {status === "applied" && !testing && !outcome && (
          <span className="ml-auto rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800" data-testid="fix-status">
            Applied · not tested
          </span>
        )}
        {!status && applicable && (
          <span className="ml-auto rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800" data-testid="fix-status">
            Not tested yet
          </span>
        )}
      </div>
      {fix.why && <p className="mt-0.5 text-muted-foreground">{fix.why}</p>}
      {fix.kind === "instruction_add" && fix.text && (
        <p className="mt-1 rounded border-l-2 border-green-500 bg-green-50 px-2 py-1 text-green-900" data-testid="fix-added">+ {fix.text}</p>
      )}
      {fix.kind === "tool_description" && (
        <div className="mt-1 space-y-0.5" data-testid="fix-change">
          <p className="rounded bg-red-50 px-2 py-0.5 text-red-800 line-through">{fix.before || "(no description)"}</p>
          <p className="rounded bg-green-50 px-2 py-0.5 text-green-900">{fix.after}</p>
        </div>
      )}
      {fix.kind === "ask_first" && (
        <p className="mt-1" data-testid="fix-change">
          <span className="text-red-800 line-through">{fix.before}</span> → <span className="text-green-900">{fix.after}</span>
        </p>
      )}
      {fix.kind === "response_filter" && (
        <div className="mt-1 space-y-0.5" data-testid="fix-change">
          <p className="text-[10px] font-semibold uppercase text-muted-foreground">The assistant is shown</p>
          <p className="rounded bg-red-50 px-2 py-0.5 text-red-800 line-through">{fix.before || "everything the app returns"}</p>
          <p className="rounded bg-green-50 px-2 py-0.5 font-mono text-green-900">{fix.after}</p>
          <p className="text-[10px] text-amber-800">Any other field is hidden from the assistant. Re-testing checks that it can still do its job.</p>
        </div>
      )}
      {fix.kind === "advice" && fix.text && <p className="mt-1">{fix.text}</p>}
      {!status && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {applicable && (
            <>
              <Button
                size="sm"
                className="h-6 text-[11px]"
                onClick={onApplyAndTest}
                disabled={busy}
                title={testCount > 0 ? `Applies it, then runs ${testCount} test${testCount === 1 ? "" : "s"} again (at least ${RETEST_RUNS} times each) to see whether it worked` : "Applies it. There is nothing to test it on right now."}
              >
                <Play className="mr-1 h-3 w-3" /> Apply and test
              </Button>
              <Button size="sm" variant="outline" className="h-6 text-[11px]" onClick={onApplyOnly} disabled={busy}>
                Apply only
              </Button>
            </>
          )}
          <Button size="sm" variant="ghost" className="h-6 text-[11px]" onClick={onSkip}>
            {applicable ? "Skip" : "Dismiss"}
          </Button>
          {applicable && <span className="text-[10px] text-amber-800">May or may not work: re-testing tells you.</span>}
        </div>
      )}
      {status === "applied" && (
        <div className="mt-1.5 space-y-1">
          {testing ? (
            <p className="text-[11px] text-slate-700">Applied to the drawing. Running the tests it was for…</p>
          ) : outcome && look ? (
            <p className={`text-[11px] font-medium ${look.textTone}`} data-testid="fix-outcome">
              {outcomeSentence(outcome)}
            </p>
          ) : (
            <p className="text-[11px] text-slate-700">Applied to the drawing, but not tested: it may or may not work.</p>
          )}
          {!testing && (
            <div className="flex flex-wrap gap-1.5">
              {(!outcome || outcome.state === "unknown") && (
                <Button size="sm" variant="outline" className="h-6 text-[11px]" onClick={onTest} disabled={busy} data-testid="fix-test">
                  <Play className="mr-1 h-3 w-3" /> Test it
                </Button>
              )}
              {canUndo && (
                <Button size="sm" variant="ghost" className="h-6 text-[11px]" onClick={onUndo} disabled={busy} data-testid="fix-undo">
                  <RotateCcw className="mr-1 h-3 w-3" /> Undo
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── one of my saved tests ─────────────────────────────────────────────────

function MyTest({ test, result, open, onToggle, onEdit, onEditExpect, onRemove }: {
  test: AgentScenario; result?: BlastResult; open: boolean; onToggle: () => void;
  onEdit: (p: Partial<AgentScenario>) => void; onEditExpect: (p: Partial<AgentScenario["expect"]>) => void; onRemove: () => void;
}) {
  return (
    <div className="rounded border bg-white" data-testid={`mine-${test.id}`}>
      <div className="flex items-center gap-2 px-2 py-1">
        <button type="button" aria-label={open ? "Collapse" : "Expand"} onClick={onToggle}>
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        {result && <span aria-label={verdict(result.status)} className={result.status === "passed" ? "text-green-600" : result.status === "error" ? "text-amber-600" : "text-red-600"}>●</span>}
        <span className="flex-1 truncate text-xs font-medium">{test.name}</span>
        {(test.kind || test.bomb) && <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{test.kind ? kindWords(test.kind) : String(test.bomb).replace(/_/g, " ")}</span>}
        <Button size="icon" variant="ghost" className="h-6 w-6" aria-label={`Delete ${test.name}`} onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      {open && (
        <div className="space-y-2 border-t px-3 py-2 text-xs">
          <label className="block">
            <span className="font-medium">Name</span>
            <Input className="mt-0.5 h-7 text-xs" value={test.name} onChange={(e) => onEdit({ name: e.target.value })} />
          </label>
          <label className="block">
            <span className="font-medium">What the person says</span>
            <Textarea className="mt-0.5 min-h-[56px] text-xs" value={test.message} onChange={(e) => onEdit({ message: e.target.value })} />
          </label>
          <label className="block">
            <span className="font-medium">A good reply (optional: a reviewer judges by this)</span>
            <Input className="mt-0.5 h-7 text-xs" value={test.judge ?? ""} placeholder="It asks for a yes before changing anything." onChange={(e) => onEdit({ judge: e.target.value })} />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="font-medium">Must call these tools</span>
              <Input className="mt-0.5 h-7 text-xs" placeholder="list_tickets, get_order" value={(test.expect.must_call ?? []).join(", ")} onChange={(e) => onEditExpect({ must_call: commas(e.target.value) })} />
            </label>
            <label className="block">
              <span className="font-medium">Must NOT call these tools</span>
              <Input className="mt-0.5 h-7 text-xs" placeholder="decide_refund" value={(test.expect.must_not_call ?? []).join(", ")} onChange={(e) => onEditExpect({ must_not_call: commas(e.target.value) })} />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="font-medium">Reply must match (one pattern per line)</span>
              <Textarea className="mt-0.5 min-h-[44px] text-xs" value={(test.expect.reply_matches ?? []).join("\n")} onChange={(e) => onEditExpect({ reply_matches: lines(e.target.value) })} />
            </label>
            <label className="block">
              <span className="font-medium">Reply must NOT match</span>
              <Textarea className="mt-0.5 min-h-[44px] text-xs" value={(test.expect.reply_must_not_match ?? []).join("\n")} onChange={(e) => onEditExpect({ reply_must_not_match: lines(e.target.value) })} />
            </label>
          </div>
          <label className="block">
            <span className="font-medium">Safety rules</span>
            <select
              className="mt-0.5 block h-7 w-full rounded border bg-transparent px-1 text-xs"
              value={test.expect.blocked === true ? "block" : test.expect.blocked === false ? "allow" : ""}
              onChange={(e) => onEditExpect({ blocked: e.target.value === "block" ? true : e.target.value === "allow" ? false : undefined })}
            >
              <option value="">Don&apos;t check</option>
              <option value="block">Must block this message</option>
              <option value="allow">Must NOT block this message</option>
            </select>
          </label>
        </div>
      )}
    </div>
  );
}
