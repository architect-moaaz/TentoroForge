"use client";
/**
 * The handoff inbox — conversations an AI agent passed to a person. Forge runtime — do not remove.
 *
 * Whoever the agent's human-handoff settings name can open it, see why someone asked for a person, how to
 * reach them and the conversation so far, then claim it, hand it back, or resolve it with a note. They can also
 * write to the person: the message appears in the person's own chat, where the assistant spoke, and what the
 * person writes back appears here (this page checks every few seconds while a conversation is open).
 * Colours come from the app's own design tokens.
 */
import * as React from "react";

type Handoff = {
  id: string;
  ref: string;
  agentId: string;
  requestedById: string;
  requestedByName?: string | null;
  reason: string;
  urgency: "low" | "normal" | "urgent";
  contact?: string | null;
  summary?: string | null;
  status: "open" | "claimed" | "resolved";
  assignedToId?: string | null;
  assignedToName?: string | null;
  resolutionNote?: string | null;
  createdAt: string;
};
type Message = { role: "user" | "assistant" | "human"; content: string };

const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "") as string;
const tok = (name: string, fallback: string) => `hsl(var(--${name}, ${fallback}))`;
const C = {
  primary: tok("primary", "221 83% 53%"),
  onPrimary: tok("primary-foreground", "0 0% 100%"),
  card: tok("card", "0 0% 100%"),
  text: tok("foreground", "222 15% 17%"),
  muted: tok("muted", "220 20% 91%"),
  mutedText: tok("muted-foreground", "223 10% 40%"),
  border: tok("border", "220 14% 87%"),
  danger: tok("destructive", "0 72% 51%"),
};
const HEADING = "var(--font-heading, inherit)";

/** **bold** as bold; everything else as written (the assistant writes light markdown). */
const bold = (text: string): React.ReactNode[] =>
  text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );

const when = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString();
};

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${BASE}/api/agent/handoffs${path}`, { credentials: "same-origin", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.error ?? "Something went wrong.");
  return body;
}

export default function HandoffsPage() {
  const [filter, setFilter] = React.useState<"active" | "resolved">("active");
  const [rows, setRows] = React.useState<Handoff[] | null>(null);
  const [me, setMe] = React.useState<{ id: string; name?: string | null } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<{ handoff: Handoff; messages: Message[] } | null>(null);
  const [note, setNote] = React.useState("");
  const [reply, setReply] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const endRef = React.useRef<HTMLDivElement>(null);

  // A bell notification links here with ?id=<handoff>: open that one straight away.
  React.useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (id) setOpenId(id);
  }, []);

  const load = React.useCallback(async () => {
    try {
      const r = await api(`?status=${filter}`);
      setRows(r.handoffs ?? []);
      setMe(r.me ?? null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRows([]);
    }
  }, [filter]);

  React.useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  const loadDetail = React.useCallback(() => {
    if (!openId) return Promise.resolve();
    return api(`?id=${encodeURIComponent(openId)}`)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [openId]);

  React.useEffect(() => {
    if (!openId) return setDetail(null);
    loadDetail();
  }, [openId, rows, loadDetail]);

  // What the person writes back shows up without a refresh: look again every few seconds while one is open.
  React.useEffect(() => {
    if (!openId || detail?.handoff.status === "resolved") return;
    const t = setInterval(loadDetail, 4000);
    return () => clearInterval(t);
  }, [openId, detail?.handoff.status, loadDetail]);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [detail?.messages.length, openId]);

  async function send() {
    const text = reply.trim();
    if (!detail || !text) return;
    setBusy(true);
    try {
      await api("", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: detail.handoff.id, action: "reply", text }),
      });
      setReply("");
      setError(null);
      await Promise.all([loadDetail(), load()]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function act(action: "claim" | "release" | "resolve") {
    if (!detail) return;
    setBusy(true);
    try {
      await api("", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: detail.handoff.id, action, note: action === "resolve" ? note : undefined }),
      });
      setNote("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const mine = detail?.handoff.assignedToId && me && detail.handoff.assignedToId === me.id;
  const pill = (text: string, tone: "plain" | "urgent" = "plain") => (
    <span
      className="rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={tone === "urgent" ? { background: C.danger, color: C.onPrimary } : { background: C.muted, color: C.mutedText }}
    >
      {text}
    </span>
  );

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4" style={{ color: C.text }}>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold" style={{ fontFamily: HEADING }}>
          Handoffs
        </h1>
        <p className="text-sm" style={{ color: C.mutedText }}>
          Conversations the assistant passed to a person.
        </p>
        <div className="ml-auto flex gap-1">
          {(["active", "resolved"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => {
                setFilter(f);
                setOpenId(null);
              }}
              className="rounded-lg px-3 py-1 text-sm"
              style={filter === f ? { background: C.primary, color: C.onPrimary } : { background: C.muted, color: C.text }}
            >
              {f === "active" ? "Waiting and in progress" : "Resolved"}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: C.border, color: C.danger }}>
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-2">
          {rows === null && <p className="text-sm" style={{ color: C.mutedText }}>Loading…</p>}
          {rows?.length === 0 && !error && (
            <p className="rounded-lg border p-4 text-sm" style={{ borderColor: C.border, color: C.mutedText }}>
              {filter === "active" ? "Nothing is waiting. New handoffs appear here and ring the bell." : "No resolved handoffs yet."}
            </p>
          )}
          {rows?.map((h) => (
            <button
              key={h.id}
              type="button"
              onClick={() => setOpenId(h.id)}
              className="block w-full rounded-lg border p-3 text-left"
              style={{ background: C.card, borderColor: openId === h.id ? C.primary : C.border }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{h.ref}</span>
                {h.urgency === "urgent" ? pill("urgent", "urgent") : h.urgency === "low" ? pill("low") : null}
                {pill(h.status === "claimed" ? `with ${h.assignedToName ?? "someone"}` : h.status)}
                <span className="ml-auto text-xs" style={{ color: C.mutedText }}>{when(h.createdAt)}</span>
              </div>
              <div className="mt-1 text-sm">{h.requestedByName ?? "Someone"}: {h.reason}</div>
            </button>
          ))}
        </div>

        <div className="rounded-lg border p-4" style={{ background: C.card, borderColor: C.border }}>
          {!detail && <p className="text-sm" style={{ color: C.mutedText }}>Pick a handoff to read the conversation.</p>}
          {detail && (
            <div className="space-y-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold tracking-wide">{detail.handoff.ref}</h2>
                  {detail.handoff.urgency === "urgent" && pill("urgent", "urgent")}
                  {pill(detail.handoff.status)}
                </div>
                <p className="mt-1 text-sm">{detail.handoff.reason}</p>
                <p className="mt-1 text-xs" style={{ color: C.mutedText }}>
                  From {detail.handoff.requestedByName ?? "someone"}
                  {detail.handoff.contact ? ` · reach them at ${detail.handoff.contact}` : ""} · {when(detail.handoff.createdAt)}
                  {detail.handoff.assignedToName ? ` · with ${detail.handoff.assignedToName}` : ""}
                </p>
                {detail.handoff.resolutionNote && (
                  <p className="mt-2 rounded px-2 py-1 text-sm" style={{ background: C.muted }}>Resolved: {detail.handoff.resolutionNote}</p>
                )}
              </div>

              <div className="max-h-72 space-y-2 overflow-y-auto rounded border p-2" style={{ borderColor: C.border }}>
                {detail.messages.map((m, i) => (
                  <div key={i} className={m.role === "user" ? "flex justify-start" : "flex justify-end"}>
                    <div
                      className="max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-1.5 text-sm"
                      style={
                        m.role === "user"
                          ? { background: C.muted }
                          : m.role === "human"
                            ? { background: C.primary, color: C.onPrimary }
                            : { background: C.card, border: `1px solid ${C.border}` }
                      }
                    >
                      <div className="text-[10px] opacity-70">
                        {m.role === "user" ? detail.handoff.requestedByName ?? "Customer" : m.role === "human" ? detail.handoff.assignedToName ?? "Team" : "Assistant"}
                      </div>
                      {bold(m.content)}
                    </div>
                  </div>
                ))}
                <div ref={endRef} />
              </div>

              {detail.handoff.status !== "resolved" && (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-2">
                    {detail.handoff.status === "open" && (
                      <button type="button" disabled={busy} onClick={() => act("claim")} className="rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50" style={{ background: C.primary, color: C.onPrimary }}>
                        Claim it
                      </button>
                    )}
                    {detail.handoff.status === "claimed" && !mine && (
                      <button type="button" disabled={busy} onClick={() => act("claim")} className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50" style={{ borderColor: C.border }}>
                        Take it over
                      </button>
                    )}
                    {detail.handoff.status === "claimed" && (
                      <button type="button" disabled={busy} onClick={() => act("release")} className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-50" style={{ borderColor: C.border }}>
                        Hand it back to the queue
                      </button>
                    )}
                  </div>
                  <div className="flex items-end gap-2">
                    <textarea
                      value={reply}
                      onChange={(e) => setReply(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          send();
                        }
                      }}
                      placeholder={mine || detail.handoff.status === "open" ? "Write to them. They see it in their chat." : "Take it over to write to them."}
                      aria-label="Message to the person"
                      disabled={detail.handoff.status === "claimed" && !mine}
                      className="min-h-[56px] w-full rounded-lg border bg-transparent px-3 py-2 text-sm disabled:opacity-50"
                      style={{ borderColor: C.border }}
                    />
                    <button type="button" disabled={busy || !reply.trim() || (detail.handoff.status === "claimed" && !mine)} onClick={send} className="rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50" style={{ background: C.primary, color: C.onPrimary }}>
                      Send
                    </button>
                  </div>
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="How was it resolved? The person sees this."
                    aria-label="Resolution note"
                    className="min-h-[56px] w-full rounded-lg border bg-transparent px-3 py-2 text-sm"
                    style={{ borderColor: C.border }}
                  />
                  <button type="button" disabled={busy} onClick={() => act("resolve")} className="rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50" style={{ background: C.primary, color: C.onPrimary }}>
                    Resolve
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
