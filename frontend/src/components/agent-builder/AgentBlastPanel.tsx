"use client";

/**
 * Find problems: throw bombs at your agent and see what explodes.
 *
 * An AI invents awkward conversations on purpose, each one a "bomb" of a kind (a made-up id, a sneaky instruction, too
 * much power, a change without asking, a secret, a plea for a person, a vague ask, a pushy "I'm the admin"). They are
 * thrown at the agent as drawn (a real model call each; tools are reported, never run) and each ends DEFUSED or
 * EXPLODED, with why. Failures come with proposed fixes: apply one to the drawing or skip it. Your own saved tests live
 * here too ("My tests") and run in the same round. Nothing is applied by itself.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle, AlertTriangle, Bomb as BombIcon, Check, ChevronDown, ChevronRight, EyeOff, Flame, Hash, HelpCircle, KeyRound, Loader2, PauseCircle,
  Play, Plus, Save, ShieldAlert, ShieldCheck, Sparkles, Trash2, User, Wrench, Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { parseEvents } from "@/lib/agent-live";
import {
  emptyBlast, estimateCalls, fixKindLabel, isBad, reduceBlast, roundSummary, tally, verdict,
  type BlastFix, type BlastResult, type BlastState, type BlastTest, type Bomb,
} from "@/lib/agent-blast";
import type { AgentScenario } from "@/types/agent-builder";

interface Props {
  projectId: string;
  agentId: string;
  /** The agent as drawn (edits that are not saved yet included): what the bombs are thrown at. */
  graph: Record<string, unknown>;
  /** Apply a proposed fix to the drawing. */
  onApplyFix: (fix: BlastFix) => void;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const FALLBACK_LIMITS = { maxTests: 20, maxRepeats: 3, perBomb: 2 };

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  hash: Hash, "eye-off": EyeOff, "shield-alert": ShieldAlert, "pause-circle": PauseCircle, key: KeyRound, user: User, "help-circle": HelpCircle, zap: Zap,
};

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);
const commas = (text: string) => text.split(",").map((l) => l.trim()).filter(Boolean);
const newId = () => `scn_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`;
const toolCount = (graph: Record<string, unknown>) => ((graph.nodes as Array<{ data?: { nodeType?: string } }> | undefined) ?? []).filter((n) => n?.data?.nodeType === "tool").length;

const asMessage = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function AgentBlastPanel({ projectId, agentId, graph, onApplyFix }: Props) {
  const base = `/api/projects/${projectId}/agent-definitions`;
  const [bombs, setBombs] = useState<Bomb[]>([]);
  const [limits, setLimits] = useState(FALLBACK_LIMITS);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [repeats, setRepeats] = useState(1);
  const [includeMine, setIncludeMine] = useState(true);
  const [mine, setMine] = useState<AgentScenario[]>([]);
  const [mineLoaded, setMineLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [state, setState] = useState<BlastState>(emptyBlast());
  // The round's state is changed in ONE place and read back from the ref: a React state updater runs later, so a value
  // read out of one (the results, to ask for fixes) would still be empty when it is wanted.
  const stateRef = useRef<BlastState>(state);
  const update = useCallback((change: (s: BlastState) => BlastState) => {
    stateRef.current = change(stateRef.current);
    setState(stateRef.current);
  }, []);
  const [invented, setInvented] = useState<BlastTest[]>([]);
  const [fixes, setFixes] = useState<BlastFix[]>([]);
  const [handled, setHandled] = useState<Record<string, "applied" | "skipped">>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [showMine, setShowMine] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const busy = state.phase === "inventing" || state.phase === "running" || state.phase === "fixing";
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
      .get<{ bombs?: Bomb[]; maxTests?: number; maxRepeats?: number; perBomb?: number }>(`${base}/blast/bombs`)
      .then((r) => {
        if (!live.current) return;
        const list = r?.bombs ?? [];
        setBombs(list);
        setPicked(new Set(list.map((b) => b.key)));
        setLimits({ maxTests: r?.maxTests ?? FALLBACK_LIMITS.maxTests, maxRepeats: r?.maxRepeats ?? FALLBACK_LIMITS.maxRepeats, perBomb: r?.perBomb ?? FALLBACK_LIMITS.perBomb });
      })
      .catch(() => live.current && setNote("The kinds of bomb could not be loaded."));
  }, [base]);

  // my saved tests
  useEffect(() => {
    api
      .get<{ scenarios?: AgentScenario[] }>(`${base}/${agentId}/tests`)
      .then((r) => live.current && setMine(Array.isArray(r?.scenarios) ? r.scenarios : []))
      .catch(() => {})
      .finally(() => live.current && setMineLoaded(true));
  }, [base, agentId]);

  const tools = toolCount(graph);
  const inventing = Math.min(picked.size * limits.perBomb, limits.maxTests);
  const runnableMine = includeMine ? mine.filter((s) => s.message.trim()).length : 0;
  const estimate = estimateCalls(inventing + runnableMine, repeats, inventing);
  const held = useMemo(() => tally(state.results), [state.results]);
  const bad = useMemo(() => Object.values(state.results).filter(isBad), [state.results]);
  const allTests = useMemo(() => [...invented, ...mine] as BlastTest[], [invented, mine]);
  const testOf = (id: string) => allTests.find((t) => t.id === id);

  // ── fixes ───────────────────────────────────────────────────────────────

  const fetchFixes = useCallback(
    async (results: BlastResult[]) => {
      const failing = results.filter(isBad);
      if (failing.length === 0) return setFixes([]);
      update((s) => ({ ...s, phase: "fixing" }));
      try {
        const r = await api.post<{ fixes?: BlastFix[] }>(`${base}/${agentId}/blast/fixes`, { graph, results: failing });
        if (!live.current) return;
        setFixes(r?.fixes ?? []);
        setHandled({});
        if (!(r?.fixes ?? []).length) setNote("It could not think of a safe fix for these. Look at the failures below.");
      } catch (e) {
        if (live.current) setNote(`Could not propose fixes: ${asMessage(e)}`);
      } finally {
        if (live.current) update((s) => ({ ...s, phase: "done" }));
      }
    },
    [base, agentId, graph, update],
  );

  // ── throwing ────────────────────────────────────────────────────────────

  const run = useCallback(
    async (tests: Array<BlastTest | AgentScenario>, opts: { merge?: boolean; withFixes?: boolean } = {}) => {
      const token = typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
      update((s) => reduceBlast({ ...s, phase: "running" }, { type: "start", total: tests.length, repeats }, opts));
      try {
        const res = await fetch(`${API_BASE}${base}/${agentId}/blast/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ graph, tests, repeats }),
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
            update((s) => reduceBlast(s, ev, opts));
          }
        }
        if (!ended) update((s) => reduceBlast(s, { type: "error", message: "The run ended without finishing." }));
        else if (opts.withFixes !== false) await fetchFixes(Object.values(stateRef.current.results));
      } catch (e) {
        if (live.current) update((s) => reduceBlast(s, { type: "error", message: asMessage(e) }));
      }
    },
    [base, agentId, graph, repeats, fetchFixes, update],
  );

  const blast = async () => {
    setNote(null);
    setFixes([]);
    setHandled({});
    setInvented([]);
    update(() => ({ ...emptyBlast(), phase: "inventing" }));
    try {
      const r = await api.post<{ tests?: BlastTest[] }>(`${base}/${agentId}/blast/invent`, { graph, bombs: [...picked], per_bomb: limits.perBomb });
      if (!live.current) return;
      const tests = r?.tests ?? [];
      setInvented(tests);
      const ready = includeMine ? [...tests, ...mine.filter((s) => s.message.trim())] : tests;
      await run(ready);
    } catch (e) {
      if (live.current) update((s) => reduceBlast(s, { type: "error", message: asMessage(e) }));
    }
  };

  const runMine = () => {
    setNote(null);
    setFixes([]);
    void run(mine.filter((s) => s.message.trim()));
  };

  const rerunBad = () => {
    setNote(null);
    const ids = new Set(bad.map((r) => r.id));
    void run(allTests.filter((t) => ids.has(t.id)), { merge: true });
  };

  // ── my tests (saved) ────────────────────────────────────────────────────

  const edit = useCallback((id: string, patch: Partial<AgentScenario>) => {
    setMine((all) => all.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    setDirty(true);
  }, []);
  const editExpect = useCallback((id: string, patch: Partial<AgentScenario["expect"]>) => {
    setMine((all) => all.map((s) => (s.id === id ? { ...s, expect: { ...s.expect, ...patch } } : s)));
    setDirty(true);
  }, []);
  const addMine = () => {
    const id = newId();
    setMine((all) => [...all, { id, name: "New test", message: "", expect: {} }]);
    setOpen((o) => ({ ...o, [`mine:${id}`]: true }));
    setShowMine(true);
    setDirty(true);
  };
  const removeMine = (id: string) => {
    setMine((all) => all.filter((s) => s.id !== id));
    setDirty(true);
  };
  const suggestFromTools = async () => {
    setNote(null);
    try {
      const r = await api.post<{ scenarios?: AgentScenario[] }>(`${base}/suggest-scenarios`, graph);
      const have = new Set(mine.map((s) => s.id));
      const fresh = (r?.scenarios ?? []).filter((s) => !have.has(s.id));
      if (fresh.length) {
        setMine((all) => [...all, ...fresh]);
        setDirty(true);
        setShowMine(true);
      }
      setNote(fresh.length ? `Added ${fresh.length} test${fresh.length === 1 ? "" : "s"} drawn from this agent's tools. They cost nothing to make.` : "Nothing new to add: you already have them all.");
    } catch (e) {
      setNote(`Could not suggest tests: ${asMessage(e)}`);
    }
  };
  const saveMine = async () => {
    setNote(null);
    try {
      const r = await api.put<{ scenarios?: AgentScenario[] }>(`${base}/${agentId}/tests`, { scenarios: mine });
      if (Array.isArray(r?.scenarios)) setMine(r.scenarios);
      setDirty(false);
      setNote("Saved.");
    } catch (e) {
      setNote(`Could not save: ${asMessage(e)}`);
    }
  };
  /** A bomb worth keeping becomes one of my tests: it runs in every round from now on. */
  const keep = (id: string) => {
    const t = invented.find((x) => x.id === id);
    if (!t || mine.some((s) => s.id === id)) return;
    setMine((all) => [...all, { id: t.id, name: t.name, message: t.message, expect: t.expect as AgentScenario["expect"], ...(t.judge ? { judge: t.judge } : {}), ...(t.bomb ? { bomb: t.bomb } : {}) }]);
    setDirty(true);
    setNote("Kept. Save your tests to keep it for later.");
  };

  // ── fixes ───────────────────────────────────────────────────────────────

  const apply = (fix: BlastFix) => {
    onApplyFix(fix);
    setHandled((h) => ({ ...h, [fix.id]: "applied" }));
  };
  const appliedAny = Object.values(handled).includes("applied");
  const pending = fixes.filter((f) => !handled[f.id]);

  // ── what to show ────────────────────────────────────────────────────────

  const nothingYet = state.order.length === 0 && state.phase === "idle";
  const exploded = held.failed + held.flaky;
  const progress = `${state.order.length} of ${state.total}`;

  return (
    <div className="flex h-full flex-col overflow-hidden" data-testid="agent-blast">
      {/* The button */}
      <div className="space-y-2 border-b px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <BombIcon className="h-4 w-4 text-red-600" />
          <h3 className="mr-auto text-sm font-semibold">Find problems</h3>
          {dirty && <span className="text-xs text-amber-700">Unsaved tests</span>}
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

      {/* The round */}
      {(note || state.order.length > 0 || busy || state.error) && (
        <div className="border-b px-3 py-1.5 text-xs" role="note" data-testid="blast-status">
          {state.phase === "inventing" && (
            <span className="flex items-center gap-1.5 font-medium">
              <BombIcon className="h-3.5 w-3.5 animate-pulse text-red-600" /> The AI is writing the bombs…
            </span>
          )}
          {state.phase === "running" && (
            <span className="flex items-center gap-1.5 font-medium">
              <Flame className="h-3.5 w-3.5 animate-pulse text-orange-500" /> Throwing bombs… {progress}
            </span>
          )}
          {state.phase === "fixing" && (
            <span className="flex items-center gap-1.5 font-medium">
              <Wrench className="h-3.5 w-3.5 animate-pulse" /> Working out fixes…
            </span>
          )}
          {state.phase !== "inventing" && state.order.length > 0 && !busy && (
            <span className={`font-medium ${exploded ? "text-red-700" : held.error ? "text-amber-700" : "text-green-700"}`} data-testid="blast-summary">
              {roundSummary(held)}
            </span>
          )}
          {state.error && (
            <span role="alert" className="font-medium text-red-700">
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
              {mine.length ? `, plus your ${mine.length} saved test${mine.length === 1 ? "" : "s"}` : ""}. Or start free:
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={suggestFromTools}>
                <Sparkles className="mr-1 h-3.5 w-3.5" /> Make tests from this agent&apos;s tools (free, no AI)
              </Button>
              <Button size="sm" variant="outline" onClick={addMine}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Write my own
              </Button>
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
                  onKeep={() => keep(id)}
                  test={testOf(id)}
                />
              ))}
          </div>
        )}

        {/* Fixes */}
        {fixes.length > 0 && (
          <div className="space-y-1.5" data-testid="blast-fixes">
            <div className="flex items-center gap-2">
              <Wrench className="h-3.5 w-3.5" />
              <h4 className="text-xs font-semibold">Proposed fixes</h4>
              <span className="text-[11px] text-muted-foreground">Nothing is applied until you say so.</span>
              {appliedAny && (
                <Button size="sm" variant="outline" className="ml-auto h-6 text-[11px]" onClick={rerunBad} disabled={busy}>
                  <Play className="mr-1 h-3 w-3" /> Re-run the {bad.length} that went off
                </Button>
              )}
            </div>
            {fixes.map((f) => (
              <FixCard key={f.id} fix={f} status={handled[f.id]} onApply={() => apply(f)} onSkip={() => setHandled((h) => ({ ...h, [f.id]: "skipped" }))} />
            ))}
            {pending.length === 0 && !appliedAny && <p className="text-[11px] text-muted-foreground">You skipped them all.</p>}
          </div>
        )}

        {/* My tests */}
        <div className="rounded border" data-testid="blast-mine">
          <div className="flex flex-wrap items-center gap-2 px-2 py-1.5">
            <button type="button" className="flex items-center gap-1 text-xs font-semibold" aria-expanded={showMine} onClick={() => setShowMine((v) => !v)}>
              {showMine ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              My tests ({mine.length})
            </button>
            <span className="text-[11px] text-muted-foreground">Saved conversations that run in every round, against the same simulated app.</span>
            <div className="ml-auto flex gap-1">
              <Button size="sm" variant="ghost" className="h-6 text-[11px]" onClick={suggestFromTools}>
                <Sparkles className="mr-1 h-3 w-3" /> From tools
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-[11px]" onClick={addMine}>
                <Plus className="mr-1 h-3 w-3" /> Add
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-[11px]" onClick={saveMine} disabled={!dirty}>
                <Save className="mr-1 h-3 w-3" /> Save
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-[11px]" onClick={runMine} disabled={busy || mine.filter((s) => s.message.trim()).length === 0}>
                <Play className="mr-1 h-3 w-3" /> Run mine
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

// ── one bomb that went off, or was defused ────────────────────────────────

function ResultCard({ result, open, onToggle, bombs, canKeep, onKeep, test }: {
  result: BlastResult; open: boolean; onToggle: () => void; bombs: Bomb[]; canKeep: boolean; onKeep: () => void; test?: BlastTest;
}) {
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
        {kind && <span className="hidden text-[10px] text-muted-foreground sm:inline">{kind.title}</span>}
        {(result.runs ?? 1) > 1 && <span className="text-[10px] text-muted-foreground">{result.passedRuns} of {result.runs} held</span>}
      </button>
      {result.status !== "passed" && (
        <ul className="mx-2 mb-1.5 space-y-0.5 text-xs" data-testid="blast-why">
          {result.status === "error" ? <li className="text-slate-700">{result.error}</li> : result.failures.map((f, i) => <li key={i} className="text-red-800">{f}</li>)}
        </ul>
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
          {canKeep && (
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

function FixCard({ fix, status, onApply, onSkip }: { fix: BlastFix; status?: "applied" | "skipped"; onApply: () => void; onSkip: () => void }) {
  const applicable = fix.kind !== "advice";
  return (
    <div className={`rounded border p-2 text-xs ${status === "applied" ? "border-green-300 bg-green-50" : status === "skipped" ? "opacity-50" : "bg-white"}`} data-testid="blast-fix" data-handled={status ?? ""}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase">{fixKindLabel(fix.kind)}</span>
        <span className="font-medium">{fix.title}</span>
        {fix.tool && <span className="font-mono text-[10px] text-muted-foreground">{fix.tool}</span>}
        {fix.fixesTests.length > 0 && <span className="text-[10px] text-muted-foreground">helps {fix.fixesTests.length} test{fix.fixesTests.length === 1 ? "" : "s"}</span>}
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
      {fix.kind === "advice" && fix.text && <p className="mt-1">{fix.text}</p>}
      {!status && (
        <div className="mt-1.5 flex gap-1.5">
          {applicable && (
            <Button size="sm" className="h-6 text-[11px]" onClick={onApply}>
              Apply to the drawing
            </Button>
          )}
          <Button size="sm" variant="ghost" className="h-6 text-[11px]" onClick={onSkip}>
            {applicable ? "Skip" : "Dismiss"}
          </Button>
        </div>
      )}
      {status === "applied" && <p className="mt-1 text-[11px] font-medium text-green-800">Applied to the drawing. Save the agent to keep it.</p>}
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
        {test.bomb && <span className="text-[10px] text-muted-foreground">{test.bomb.replace(/_/g, " ")}</span>}
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
