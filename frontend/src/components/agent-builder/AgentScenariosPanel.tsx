"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Loader2, Play, Plus, Save, Sparkles, Trash2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { AgentScenario, AgentScenarioResult } from "@/types/agent-builder";

interface AgentScenariosPanelProps {
  projectId: string;
  agentId: string;
  /** The agent as drawn (edits that are not saved yet included): what the scenarios run against. */
  graph: Record<string, unknown>;
}

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);
const commas = (text: string) => text.split(",").map((l) => l.trim()).filter(Boolean);

const newId = () => `scn_${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`;

/**
 * Saved test conversations: what to say to the agent and what must (not) happen. They run against the agent
 * as drawn with the Test console's dry run, so a change can be checked in a minute and the same checks run
 * again after the next change. Tools the model asks for are reported and never executed.
 */
export function AgentScenariosPanel({ projectId, agentId, graph }: AgentScenariosPanelProps) {
  const base = `/api/projects/${projectId}/agent-definitions`;
  const [scenarios, setScenarios] = useState<AgentScenario[]>([]);
  const [results, setResults] = useState<Record<string, AgentScenarioResult>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [running, setRunning] = useState<string | "all" | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<{ scenarios?: AgentScenario[] }>(`${base}/${agentId}/tests`)
      .then((r) => {
        if (live) setScenarios(Array.isArray(r?.scenarios) ? r.scenarios : []);
      })
      .catch(() => {})
      .finally(() => live && setLoaded(true));
    return () => {
      live = false;
    };
  }, [base, agentId]);

  const edit = useCallback((id: string, patch: Partial<AgentScenario>) => {
    setScenarios((all) => all.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    setDirty(true);
  }, []);
  const editExpect = useCallback((id: string, patch: Partial<AgentScenario["expect"]>) => {
    setScenarios((all) => all.map((s) => (s.id === id ? { ...s, expect: { ...s.expect, ...patch } } : s)));
    setDirty(true);
  }, []);

  const add = () => {
    const id = newId();
    setScenarios((all) => [...all, { id, name: "New scenario", message: "", expect: {} }]);
    setOpen((o) => ({ ...o, [id]: true }));
    setDirty(true);
  };

  const remove = (id: string) => {
    setScenarios((all) => all.filter((s) => s.id !== id));
    setResults((r) => {
      const { [id]: _gone, ...rest } = r;
      return rest;
    });
    setDirty(true);
  };

  const suggest = async () => {
    setNote(null);
    try {
      const r = await api.post<{ scenarios?: AgentScenario[] }>(`${base}/suggest-scenarios`, graph);
      const have = new Set(scenarios.map((s) => s.id));
      const fresh = (r?.scenarios ?? []).filter((s) => !have.has(s.id));
      if (fresh.length) {
        setScenarios((all) => [...all, ...fresh]);
        setDirty(true);
      }
      setNote(fresh.length ? `Added ${fresh.length} suggested scenario${fresh.length === 1 ? "" : "s"}.` : "Nothing new to suggest: you already have them all.");
    } catch (e) {
      setNote(`Could not suggest scenarios: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const save = async () => {
    setNote(null);
    try {
      const r = await api.put<{ scenarios?: AgentScenario[] }>(`${base}/${agentId}/tests`, { scenarios });
      if (Array.isArray(r?.scenarios)) setScenarios(r.scenarios);
      setDirty(false);
      setNote("Saved.");
    } catch (e) {
      setNote(`Could not save: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const run = async (only?: AgentScenario) => {
    setNote(null);
    setRunning(only ? only.id : "all");
    try {
      const r = await api.post<{ results?: AgentScenarioResult[] }>(`${base}/${agentId}/tests/run`, {
        graph,
        scenarios: only ? [only] : scenarios,
      });
      setResults((prev) => {
        const next = only ? { ...prev } : {};
        for (const x of r?.results ?? []) next[x.id] = x;
        return next;
      });
      if (!only) setOpen((o) => ({ ...o, ...Object.fromEntries((r?.results ?? []).filter((x) => x.status !== "passed").map((x) => [x.id, true])) }));
    } catch (e) {
      setNote(`Could not run: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRunning(null);
    }
  };

  const tally = useMemo(() => {
    const all = Object.values(results);
    return {
      total: all.length,
      passed: all.filter((r) => r.status === "passed").length,
      failed: all.filter((r) => r.status === "failed").length,
      errors: all.filter((r) => r.status === "error").length,
    };
  }, [results]);

  return (
    <div className="flex h-full flex-col overflow-hidden" data-testid="agent-scenarios">
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <h3 className="mr-auto text-sm font-semibold">Test scenarios</h3>
        {dirty && <span className="text-xs text-amber-700">Unsaved changes</span>}
        <Button size="sm" variant="outline" onClick={suggest}>
          <Sparkles className="mr-1 h-3.5 w-3.5" /> Suggest
        </Button>
        <Button size="sm" variant="outline" onClick={add}>
          <Plus className="mr-1 h-3.5 w-3.5" /> Add
        </Button>
        <Button size="sm" variant="outline" onClick={save} disabled={!dirty}>
          <Save className="mr-1 h-3.5 w-3.5" /> Save
        </Button>
        <Button size="sm" onClick={() => run()} disabled={running !== null || scenarios.length === 0}>
          {running === "all" ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1 h-3.5 w-3.5" />}
          Run all
        </Button>
      </div>

      {(note || tally.total > 0) && (
        <div className="border-b px-3 py-1.5 text-xs" role="note">
          {tally.total > 0 && (
            <span className={tally.failed || tally.errors ? "font-medium text-red-700" : "font-medium text-green-700"}>
              {tally.passed} of {tally.total} passed
              {tally.failed ? ` · ${tally.failed} failed` : ""}
              {tally.errors ? ` · ${tally.errors} could not run` : ""}
            </span>
          )}
          {note && <span className="ml-3 text-muted-foreground">{note}</span>}
        </div>
      )}

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {loaded && scenarios.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No scenarios yet. A scenario is something to say to the agent and what must (or must not) happen. Press Suggest for a starting
            set drawn from what this agent can do.
          </p>
        )}
        {scenarios.map((s) => {
          const r = results[s.id];
          const isOpen = !!open[s.id];
          return (
            <div key={s.id} className="rounded border bg-white" data-testid={`scenario-${s.id}`}>
              <div className="flex items-center gap-2 px-2 py-1.5">
                <button type="button" aria-label={isOpen ? "Collapse" : "Expand"} onClick={() => setOpen((o) => ({ ...o, [s.id]: !isOpen }))}>
                  {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </button>
                {r?.status === "passed" && <CheckCircle2 aria-label="passed" className="h-4 w-4 text-green-600" />}
                {r?.status === "failed" && <XCircle aria-label="failed" className="h-4 w-4 text-red-600" />}
                {r?.status === "error" && <AlertCircle aria-label="could not run" className="h-4 w-4 text-amber-600" />}
                <span className="flex-1 truncate text-sm font-medium">{s.name}</span>
                <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => run(s)} disabled={running !== null || !s.message.trim()}>
                  {running === s.id ? <Loader2 className="h-3 w-3 animate-spin" /> : "Run"}
                </Button>
                <Button size="icon" variant="ghost" className="h-6 w-6" aria-label={`Delete ${s.name}`} onClick={() => remove(s.id)}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>

              {r && r.status !== "passed" && (
                <ul className="mx-2 mb-1.5 space-y-0.5 text-xs text-red-700">
                  {r.status === "error" ? <li>{r.error}</li> : r.failures.map((f, i) => <li key={i}>{f}</li>)}
                </ul>
              )}

              {isOpen && (
                <div className="space-y-2 border-t px-3 py-2 text-xs">
                  <label className="block">
                    <span className="font-medium">Name</span>
                    <Input className="mt-0.5 h-7 text-xs" value={s.name} onChange={(e) => edit(s.id, { name: e.target.value })} />
                  </label>
                  <label className="block">
                    <span className="font-medium">What the person says</span>
                    <Textarea className="mt-0.5 min-h-[56px] text-xs" value={s.message} onChange={(e) => edit(s.id, { message: e.target.value })} />
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="block">
                      <span className="font-medium">Must call these tools</span>
                      <Input
                        className="mt-0.5 h-7 text-xs"
                        placeholder="list_tickets, get_order"
                        value={(s.expect.must_call ?? []).join(", ")}
                        onChange={(e) => editExpect(s.id, { must_call: commas(e.target.value) })}
                      />
                    </label>
                    <label className="block">
                      <span className="font-medium">Must NOT call these tools</span>
                      <Input
                        className="mt-0.5 h-7 text-xs"
                        placeholder="decide_refund"
                        value={(s.expect.must_not_call ?? []).join(", ")}
                        onChange={(e) => editExpect(s.id, { must_not_call: commas(e.target.value) })}
                      />
                    </label>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="block">
                      <span className="font-medium">Reply must match (one pattern per line)</span>
                      <Textarea
                        className="mt-0.5 min-h-[44px] text-xs"
                        value={(s.expect.reply_matches ?? []).join("\n")}
                        onChange={(e) => editExpect(s.id, { reply_matches: lines(e.target.value) })}
                      />
                    </label>
                    <label className="block">
                      <span className="font-medium">Reply must NOT match</span>
                      <Textarea
                        className="mt-0.5 min-h-[44px] text-xs"
                        value={(s.expect.reply_must_not_match ?? []).join("\n")}
                        onChange={(e) => editExpect(s.id, { reply_must_not_match: lines(e.target.value) })}
                      />
                    </label>
                  </div>
                  <label className="block">
                    <span className="font-medium">Safety rules</span>
                    <select
                      className="mt-0.5 block h-7 w-full rounded border bg-transparent px-1 text-xs"
                      value={s.expect.blocked === true ? "block" : s.expect.blocked === false ? "allow" : ""}
                      onChange={(e) => editExpect(s.id, { blocked: e.target.value === "block" ? true : e.target.value === "allow" ? false : undefined })}
                    >
                      <option value="">Don&apos;t check</option>
                      <option value="block">Must block this message</option>
                      <option value="allow">Must NOT block this message</option>
                    </select>
                  </label>

                  {r && (
                    <div className="rounded bg-slate-50 p-2" data-testid="scenario-result">
                      <div className="font-medium">What it did</div>
                      {r.toolCalls.length > 0 && (
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          {r.toolCalls.map((c, i) => (
                            <span key={i} className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] text-blue-700">
                              {c.name}
                            </span>
                          ))}
                        </div>
                      )}
                      {r.response && <p className="mt-1 whitespace-pre-wrap text-slate-700">{r.response.slice(0, 400)}</p>}
                      {(r.ms != null || r.tokens != null) && (
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {r.ms != null ? `${r.ms} ms` : ""} {r.tokens != null ? `· ${r.tokens} tokens` : ""}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
