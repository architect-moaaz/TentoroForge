"use client";

/**
 * Live activity — the super admin watches what a signed-in person is doing
 * across the platform, as it happens. The feed shows the action and which
 * record, never the person's private values; it is live only and keeps no
 * history, and opening it is itself recorded. The person is watched the
 * whole time this page is open on them, and the watch ends when it closes.
 */

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Radio, Search, Lock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { adminApi, adminKeys } from "@/lib/admin-api";
import type { AdminPerson } from "@/lib/admin-types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";
const MAX_ROWS = 300;

interface Activity {
  at: string;
  label: string;
  method: string;
  path: string;
  status: number;
  org: string | null;
  by: string | null;
  seq: number;
}

function timeOf(iso: string): string {
  try { return new Date(iso).toLocaleTimeString([], { hour12: false }); } catch { return ""; }
}

function LiveFeed({ person }: { person: AdminPerson }) {
  const [events, setEvents] = useState<Activity[]>([]);
  const [state, setState] = useState<"connecting" | "live" | "unavailable" | "closed">("connecting");
  const seq = useRef(0);

  useEffect(() => {
    setEvents([]);
    setState("connecting");
    seq.current = 0;
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (!token) { setState("unavailable"); return; }
    // EventSource cannot send an Authorization header; this one route takes
    // the token as a query parameter and checks it for the super admin role.
    const es = new EventSource(`${API_BASE}/api/admin/live/${person.id}?access_token=${encodeURIComponent(token)}`);
    es.addEventListener("ready", (e) => {
      try { setState(JSON.parse((e as MessageEvent).data).available ? "live" : "unavailable"); }
      catch { setState("live"); }
    });
    es.addEventListener("activity", (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        setEvents((cur) => [{ ...d, seq: seq.current++ }, ...cur].slice(0, MAX_ROWS));
      } catch { /* ignore a malformed frame */ }
    });
    es.onerror = () => setState((s) => (s === "live" ? "live" : "connecting"));
    return () => es.close();
  }, [person.id]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-1 pb-3 text-sm">
        <span className={`inline-flex h-2 w-2 rounded-full ${state === "live" ? "animate-pulse bg-emerald-500" : state === "unavailable" ? "bg-destructive" : "bg-amber-500"}`} />
        <span className="font-medium">{person.name || person.email}</span>
        <span className="text-muted-foreground">{person.email}</span>
        <span className="ml-auto text-xs text-muted-foreground">
          {state === "live" ? "watching live" : state === "connecting" ? "connecting…" : state === "unavailable" ? "live activity is unavailable (needs Redis)" : "closed"}
        </span>
      </div>
      <p className="px-1 py-2 text-xs text-muted-foreground">
        Actions and which record, as they happen. Private values are masked and nothing is stored. Your watching is on the record.
      </p>
      <div className="min-h-0 flex-1 overflow-auto rounded-lg border bg-white dark:bg-slate-900">
        {events.length === 0 ? (
          <div className="flex h-full items-center justify-center p-10 text-center text-sm text-muted-foreground">
            {state === "unavailable"
              ? "Live activity needs Redis, which is not reachable here."
              : `Waiting for ${person.name || person.email} to do something…`}
          </div>
        ) : (
          <ul className="divide-y text-sm">
            {events.map((e) => (
              <li key={e.seq} className="flex items-center gap-3 px-3 py-2">
                <span className="w-16 shrink-0 font-mono text-[11px] text-muted-foreground">{timeOf(e.at)}</span>
                <span className="font-medium">{e.label}</span>
                {e.by && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-900 dark:bg-amber-950 dark:text-amber-200">as them (admin)</span>}
                <span className="ml-auto flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                  <span>{e.method}</span>
                  <span className={e.status >= 400 ? "text-destructive" : ""}>{e.status}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function LivePageInner() {
  const params = useSearchParams();
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string>(params.get("user") || "");
  const people = useQuery({ queryKey: adminKeys.people(q, 1), queryFn: () => adminApi.people(q, 1) });
  const rows = people.data?.items ?? [];
  const person = useMemo(() => rows.find((p) => p.id === picked), [rows, picked]);

  return (
    <div className="mx-auto flex h-[calc(100vh-1px)] max-w-6xl flex-col gap-4 p-6">
      <div>
        <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-primary"><Radio className="h-3.5 w-3.5" /> Cockpit · Live</p>
        <h1 className="text-2xl font-bold tracking-tight">Watch a person, live</h1>
        <p className="text-sm text-muted-foreground">Pick someone to see what they are doing on the platform as it happens — actions and masked data, nothing stored.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-72">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder="Find a person" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {rows.slice(0, 8).map((p) => (
            <button key={p.id} onClick={() => setPicked(p.id)}
                    className={`rounded-full border px-3 py-1 text-xs ${picked === p.id ? "border-primary bg-primary/10 font-medium" : "hover:bg-muted"}`}>
              {p.name || p.email}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {person ? <LiveFeed key={person.id} person={person} /> : (
          <div className="flex h-full items-center justify-center rounded-lg border p-10 text-sm text-muted-foreground">
            <span className="flex items-center gap-2"><Lock className="h-4 w-4" /> Choose a person above to begin watching.</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function AdminLivePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading…</div>}>
      <LivePageInner />
    </Suspense>
  );
}
