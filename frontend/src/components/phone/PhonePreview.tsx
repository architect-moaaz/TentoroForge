"use client";

// The Phone tab: the app's native screens, drawn in a browser inside a phone frame, with sample data and no sign-in.
// "Use" taps through the screens; "Select" picks a part of a screen and hands Smith a request about it.
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MousePointerClick, RefreshCw, Smartphone, Hand, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useSmithDraftStore } from "@/stores/smithDraft";

const PREFIX = "design2ui:";

interface PhoneStatus {
  state: "none" | "building" | "ready" | "failed" | "unavailable";
  step?: string;
  error?: string;
  reason?: string;
  builtAt?: string | null;
  stale?: boolean;
  servePath: string;
}

interface Picked {
  tagName: string;
  textContent: string;
  source: { file: string; line: number; component: string | null } | null;
}

export function phoneStatusKey(projectId: string) {
  return ["project", projectId, "phone-preview"] as const;
}

/** The sentence handed to Smith: where the person was looking, and what they said. */
export function requestFor(route: string, picked: Picked | null, change: string): string {
  const where = route && route !== "/" ? `the phone screen at ${route}` : "the phone app's first screen";
  const text = picked?.textContent?.trim();
  const what = picked
    ? `${text ? `the part that says "${text.slice(0, 60)}"` : `a ${picked.source?.component ?? picked.tagName} element`}` +
      (picked.source ? ` (${picked.source.file}:${picked.source.line})` : "")
    : "this screen";
  return `On ${where}, ${what}: ${change.trim()}`;
}

export function PhonePreview({ projectId, onAskSmith }: { projectId: string; onAskSmith: () => void }) {
  const queryClient = useQueryClient();
  const frame = useRef<HTMLIFrameElement>(null);
  const [mode, setMode] = useState<"use" | "select">("use");
  const [route, setRoute] = useState("/");
  const [picked, setPicked] = useState<Picked | null>(null);
  const [change, setChange] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");
  const [frameKey, setFrameKey] = useState(0);
  const ask = useSmithDraftStore((s) => s.ask);

  const { data: status } = useQuery({
    queryKey: phoneStatusKey(projectId),
    queryFn: () => api.get<PhoneStatus>(`/api/projects/${projectId}/phone-preview/status`),
    refetchInterval: (q) => (q.state.data?.state === "building" ? 2000 : false),
  });

  const build = useCallback(async () => {
    setStarting(true);
    setStartError("");
    try {
      const next = await api.post<PhoneStatus>(`/api/projects/${projectId}/phone-preview/build`);
      queryClient.setQueryData(phoneStatusKey(projectId), next);
    } catch (err) {
      setStartError((err as Error).message);
    } finally {
      setStarting(false);
    }
  }, [projectId, queryClient]);

  // A first visit builds it; there is nothing to look at until then.
  const autoStarted = useRef(false);
  useEffect(() => {
    if (status?.state === "none" && !autoStarted.current) {
      autoStarted.current = true;
      void build();
    }
  }, [status?.state, build]);

  // A new build is a new page.
  useEffect(() => { if (status?.state === "ready") setFrameKey((k) => k + 1); }, [status?.builtAt, status?.state]);

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.source !== frame.current?.contentWindow) return;
      const type = typeof e.data?.type === "string" ? e.data.type : "";
      if (!type.startsWith(PREFIX)) return;
      const kind = type.slice(PREFIX.length);
      if (kind === "route") setRoute(String(e.data.payload?.path ?? "/").replace(/^.*\/phone\/serve/, "") || "/");
      if (kind === "select") setPicked(e.data.payload as Picked);
      if (kind === "deselect") setPicked(null);
      if (kind === "ready") frame.current?.contentWindow?.postMessage({ type: PREFIX + "set-mode", payload: { mode } }, "*");
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [mode]);

  const choose = (next: "use" | "select") => {
    setMode(next);
    if (next === "use") setPicked(null);
    frame.current?.contentWindow?.postMessage({ type: PREFIX + "set-mode", payload: { mode: next } }, "*");
  };

  const send = () => {
    if (!change.trim()) return;
    ask(requestFor(route, picked, change));
    setChange("");
    onAskSmith();
  };

  const src = status ? `${process.env.NEXT_PUBLIC_API_URL ?? ""}${status.servePath}/` : null;
  const building = status?.state === "building" || starting;

  return (
    <div className="flex h-full flex-col" data-testid="phone-preview">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-1">
          <Button variant={mode === "use" ? "secondary" : "ghost"} size="sm" className="h-8 text-xs" onClick={() => choose("use")}
                  disabled={status?.state !== "ready"}>
            <Hand className="mr-1 h-3.5 w-3.5" /> Use
          </Button>
          <Button variant={mode === "select" ? "secondary" : "ghost"} size="sm" className="h-8 text-xs" onClick={() => choose("select")}
                  disabled={status?.state !== "ready"}>
            <MousePointerClick className="mr-1 h-3.5 w-3.5" /> Select to change
          </Button>
        </div>
        <div className="flex items-center gap-2">
          {status?.stale && !building && (
            <span className="text-xs text-amber-600">The screens changed since this was drawn.</span>
          )}
          <Button variant={status?.stale ? "default" : "ghost"} size="sm" className="h-8 text-xs" onClick={build} disabled={building}>
            {building ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1 h-3.5 w-3.5" />}
            {building ? "Drawing…" : "Redraw"}
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex flex-1 items-center justify-center overflow-auto bg-muted/30 p-4">
          {status?.state === "unavailable" ? (
            <p className="max-w-xs text-center text-sm text-muted-foreground">{status.reason}</p>
          ) : building ? (
            <div className="flex flex-col items-center gap-2 text-center">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{status?.step || "Starting"}…</p>
              <p className="max-w-xs text-xs text-muted-foreground">
                The first time takes a few minutes: the phone screens are drawn here with sample data, so nothing real is touched.
              </p>
            </div>
          ) : status?.state === "failed" || startError ? (
            <div className="flex max-w-sm flex-col items-center gap-3 text-center">
              <Smartphone className="h-10 w-10 text-muted-foreground" />
              <p className="text-sm text-red-600">{startError || status?.error}</p>
              <Button size="sm" onClick={build}>Try again</Button>
            </div>
          ) : status?.state === "ready" && src ? (
            <div className="shrink-0 rounded-[2.5rem] border-[10px] border-slate-900 bg-slate-900 shadow-xl dark:border-slate-700">
              <iframe
                key={frameKey}
                ref={frame}
                src={src}
                title="Phone preview"
                className="block rounded-[1.9rem] bg-white"
                style={{ width: 375, height: 760 }}
              />
            </div>
          ) : (
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          )}
        </div>

        {status?.state === "ready" && (
          <aside className="flex w-72 shrink-0 flex-col gap-3 border-l p-3 text-sm">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Screen</p>
              <p className="font-mono text-xs">{route}</p>
            </div>
            {mode === "select" && !picked && (
              <p className="text-xs text-muted-foreground">Click a part of the screen to say what should change about it.</p>
            )}
            {picked && (
              <div className="rounded-md border p-2 text-xs">
                <p className="font-medium">{picked.source?.component ?? picked.tagName}</p>
                {picked.textContent && <p className="mt-0.5 text-muted-foreground">“{picked.textContent.slice(0, 80)}”</p>}
                {picked.source && <p className="mt-1 font-mono text-[11px] text-muted-foreground">{picked.source.file}:{picked.source.line}</p>}
              </div>
            )}
            <label className="text-xs text-muted-foreground" htmlFor="phone-change">What should change?</label>
            <textarea
              id="phone-change"
              value={change}
              onChange={(e) => setChange(e.target.value)}
              rows={4}
              placeholder={picked ? "Make this bigger, rename it, move it…" : "Describe a change to this screen"}
              className="w-full resize-none rounded-md border bg-background p-2 text-sm"
            />
            <Button size="sm" onClick={send} disabled={!change.trim()}>
              <Send className="mr-1 h-3.5 w-3.5" /> Ask Smith
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Sample data only: nothing here is real, and changes you make by tapping are forgotten on reload.
            </p>
            <div className="rounded-md bg-muted/50 p-2 text-[11px] text-muted-foreground">
              <p className="font-medium text-foreground">Try sign-in and sign-up</p>
              <p className="mt-0.5">
                You start signed in. Sign out from the Account tab to see those screens; any values let you back in, for example{" "}
                <span className="font-mono">preview@example.com</span> / <span className="font-mono">preview123</span>.
              </p>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
