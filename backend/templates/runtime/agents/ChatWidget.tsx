"use client";
/**
 * The chat surface for the app's AI agents. Forge runtime — do not remove.
 *
 *   <ChatWidget />                  floating button + panel, bottom corner
 *   <ChatWidget variant="page" />   fills its container (the /assistant page)
 *
 * It asks GET /api/agent/chat which agent to be and how to look (name, welcome
 * line, suggested questions), then streams POST /api/agent/chat. Colours come
 * from the app's own tokens, so it wears the app's palette.
 */
import * as React from "react";

type Ui = {
  title: string;
  subtitle?: string;
  welcomeMessage?: string;
  suggestedQuestions?: string[];
  position: "bottom-right" | "bottom-left" | "full-page";
};
type AgentInfo = { id: string; name: string; description: string | null; ui: Ui };
type ToolNote = { id: string; tool: string; state: "running" | "ok" | "failed" | "held" };
/** "human" is a person on the team who has taken the conversation over. */
type Msg = { role: "user" | "assistant" | "human"; content: string; tools?: ToolNote[]; notice?: string };
/** The conversation is with a person: where it stands, as the person who asked sees it. */
type HandoffInfo = { ref: string; status: "open" | "claimed" | "resolved"; assignedToName?: string | null; resolutionNote?: string | null };

const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "") as string;
// The app's own design tokens (HSL triples, the same ones its pages use), each with a neutral
// fallback so the widget still reads in an app that defines none of them.
const tok = (name: string, fallback: string) => `hsl(var(--${name}, ${fallback}))`;
const C = {
  primary: tok("primary", "221 83% 53%"),
  onPrimary: tok("primary-foreground", "0 0% 100%"),
  card: tok("card", "0 0% 100%"),
  text: tok("foreground", "222 15% 17%"),
  muted: tok("muted", "220 20% 91%"),
  mutedText: tok("muted-foreground", "223 10% 40%"),
  border: tok("border", "220 14% 87%"),
};
const RADIUS = "var(--radius-lg, 16px)";
const HEADING = "var(--font-heading, inherit)";

const label = (tool: string) => tool.replace(/[_-]+/g, " ");

type SavedMessage = {
  role: "user" | "assistant" | "human";
  content: string;
  toolCalls?: Array<{ name: string; error?: string | null; result?: { held?: boolean } | null }> | null;
};

/** A saved turn as the chat draws it: the words, and a chip for each tool it used. */
function fromSaved(m: SavedMessage, i: number): Msg {
  return {
    role: m.role,
    content: m.content,
    tools: (m.toolCalls ?? []).map((t, k) => ({
      id: `saved-${i}-${k}`,
      tool: t.name,
      state: t.error ? ("failed" as const) : t.result?.held ? ("held" as const) : ("ok" as const),
    })),
  };
}

// "New chat" is remembered per agent, so a reload does not bring the old conversation back.
const freshKey = (agentId: string) => `forge-agent-new:${agentId}`;
const readFresh = (agentId: string): number => {
  try {
    return Number(window.localStorage.getItem(freshKey(agentId)) ?? 0) || 0;
  } catch {
    return 0;
  }
};
const writeFresh = (agentId: string) => {
  try {
    window.localStorage.setItem(freshKey(agentId), String(Date.now()));
  } catch {
    /* private window: the old conversation simply comes back on reload */
  }
};

// ── a small, safe markdown renderer ───────────────────────────────────────
// The model writes **bold**, "- " lists, numbered lists, `code` and pipe tables. Shown as plain
// text those are stray asterisks and dashes. Built from React elements only, never HTML strings.

function inline(text: string, key: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|(?<![*\w])\*[^*\s][^*]*\*(?![*\w]))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let n = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const piece = m[0];
    const k = `${key}-${n++}`;
    if (piece.startsWith("**")) out.push(<strong key={k}>{piece.slice(2, -2)}</strong>);
    else if (piece.startsWith("`"))
      out.push(<code key={k} className="rounded px-1 text-[0.9em]" style={{ background: C.border }}>{piece.slice(1, -1)}</code>);
    else out.push(<em key={k}>{piece.slice(1, -1)}</em>);
    last = m.index + piece.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING_RE = /^#{1,4}\s+(.*)$/;
const isTableRow = (l: string) => /^\s*\|.*\|\s*$/.test(l);
const isTableRule = (l: string) => /^\s*\|[\s:|-]+\|\s*$/.test(l);

function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let b = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const key = `b${b++}`;

    if (RULE.test(line)) {
      blocks.push(<hr key={key} className="my-2" style={{ borderColor: C.border }} />);
      i++;
      continue;
    }

    if (isTableRow(line) && i + 1 < lines.length && isTableRule(lines[i + 1])) {
      const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) rows.push(cells(lines[i++]));
      const rule = { borderBottom: `1px solid ${C.border}` };
      blocks.push(
        <div key={key} className="my-1 overflow-x-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr>{head.map((h, c) => <th key={c} className="px-2 py-1 font-semibold" style={rule}>{inline(h, `${key}h${c}`)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>{r.map((c, ci) => <td key={ci} className="px-2 py-1 align-top" style={rule}>{inline(c, `${key}r${ri}c${ci}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (BULLET.test(line) || NUMBERED.test(line)) {
      const ordered = NUMBERED.test(line);
      const rx = ordered ? NUMBERED : BULLET;
      const items: string[] = [];
      while (i < lines.length && rx.test(lines[i])) items.push((lines[i++].match(rx) as RegExpMatchArray)[1]);
      const Tag = ordered ? "ol" : "ul";
      blocks.push(
        <Tag key={key} className={"my-1 space-y-1 pl-5 " + (ordered ? "list-decimal" : "list-disc")}>
          {items.map((t, k) => <li key={k}>{inline(t, `${key}i${k}`)}</li>)}
        </Tag>,
      );
      continue;
    }

    const heading = line.match(HEADING_RE);
    if (heading) {
      blocks.push(<div key={key} className="mt-1 font-semibold" style={{ fontFamily: HEADING }}>{inline(heading[1], key)}</div>);
      i++;
      continue;
    }

    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !BULLET.test(lines[i]) && !NUMBERED.test(lines[i]) && !HEADING_RE.test(lines[i]) && !RULE.test(lines[i]) && !isTableRow(lines[i])) para.push(lines[i++]);
    blocks.push(
      <p key={key} className="my-1">
        {para.map((t, k) => <React.Fragment key={k}>{k > 0 && <br />}{inline(t, `${key}p${k}`)}</React.Fragment>)}
      </p>,
    );
  }
  return <div className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{blocks}</div>;
}

export function ChatWidget({
  agentId,
  variant = "floating",
}: {
  agentId?: string;
  variant?: "floating" | "page";
}) {
  const [agent, setAgent] = React.useState<AgentInfo | null>(null);
  const [open, setOpen] = React.useState(variant === "page");
  const [msgs, setMsgs] = React.useState<Msg[]>([]);
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [handoff, setHandoff] = React.useState<HandoffInfo | null>(null);
  const endRef = React.useRef<HTMLDivElement>(null);
  const savedCount = React.useRef(0); // how many saved messages the chat has drawn

  // The bell's "New message from the team" opens this chat, so the reply is one click away.
  React.useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener("forge:open-agent-chat", show);
    return () => window.removeEventListener("forge:open-agent-chat", show);
  }, []);

  React.useEffect(() => {
    let live = true;
    fetch(`${BASE}/api/agent/chat`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : []))
      .then((list: AgentInfo[]) => {
        if (!live) return;
        const pick = agentId ? list.find((a) => a.id === agentId) : list.find((a) => a.ui.position !== "full-page") ?? list[0];
        if (!pick) return;
        setAgent(pick);
        if (pick.ui.welcomeMessage) setMsgs([{ role: "assistant", content: pick.ui.welcomeMessage }]);
        // Pick up where the person left off. A reload used to start from nothing, so the agent
        // "forgot" a conversation that was sitting in the database.
        fetch(`${BASE}/api/agent/conversations?agent=${encodeURIComponent(pick.id)}`, { credentials: "same-origin" })
          .then((r) => (r.ok ? r.json() : []))
          .then(async (list: Array<{ id: string; updatedAt?: string | null }>) => {
            const latest = Array.isArray(list) ? list[0] : undefined;
            if (!latest || !live) return;
            const touched = latest.updatedAt ? new Date(latest.updatedAt).getTime() : 0;
            if (touched <= readFresh(pick.id)) return;
            const res = await fetch(`${BASE}/api/agent/conversations?id=${encodeURIComponent(latest.id)}`, {
              credentials: "same-origin",
            });
            if (!res.ok || !live) return;
            const conv = (await res.json()) as { id: string; messages?: SavedMessage[] };
            if (!conv.messages?.length) return;
            setConversationId(conv.id);
            savedCount.current = conv.messages.length;
            setMsgs(conv.messages.map(fromSaved));
            refreshHandoff(conv.id);
          })
          .catch(() => {});
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [agentId]);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [msgs]);

  const refreshHandoff = React.useCallback(async (id: string | null) => {
    if (!id) return setHandoff(null);
    try {
      const res = await fetch(`${BASE}/api/agent/handoffs?conversation=${encodeURIComponent(id)}`, { credentials: "same-origin" });
      if (!res.ok) return;
      const body = (await res.json()) as { handoff: HandoffInfo | null };
      setHandoff(body.handoff ?? null);
    } catch {
      /* the status line is a nicety: the chat works without it */
    }
  }, []);

  // What the conversation holds now, as saved: a person on the team may have written into it.
  const refreshMessages = React.useCallback(async (id: string) => {
    try {
      const res = await fetch(`${BASE}/api/agent/conversations?id=${encodeURIComponent(id)}`, { credentials: "same-origin" });
      if (!res.ok) return;
      const conv = (await res.json()) as { messages?: SavedMessage[] };
      const saved = conv.messages ?? [];
      if (saved.length === savedCount.current) return;
      savedCount.current = saved.length;
      setMsgs(saved.map(fromSaved));
    } catch {
      /* the next look will catch up */
    }
  }, []);

  // While a conversation is with a person, look for their messages and the status every few seconds (they may write,
  // pick it up or resolve it). The look that sees "resolved" is also the last one. Never while an answer is streaming.
  React.useEffect(() => {
    if (!conversationId || !handoff || handoff.status === "resolved") return;
    const t = setInterval(() => {
      if (busy) return;
      refreshHandoff(conversationId);
      refreshMessages(conversationId);
    }, 4000);
    return () => clearInterval(t);
  }, [conversationId, handoff, busy, refreshHandoff, refreshMessages]);

  // Start over: forget this conversation here (it stays in the database) and show the welcome again.
  function newChat() {
    if (!agent || busy) return;
    writeFresh(agent.id);
    setConversationId(null);
    setHandoff(null);
    savedCount.current = 0;
    setInput("");
    setMsgs(agent.ui.welcomeMessage ? [{ role: "assistant", content: agent.ui.welcomeMessage }] : []);
  }

  // The last message is the one being written; every update replaces it.
  const patchLast = (fn: (m: Msg) => Msg) =>
    setMsgs((prev) => (prev.length ? [...prev.slice(0, -1), fn(prev[prev.length - 1])] : prev));

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy || !agent) return;
    setInput("");
    setBusy(true);
    setMsgs((p) => [...p, { role: "user", content: message }, { role: "assistant", content: "", tools: [] }]);
    try {
      const res = await fetch(`${BASE}/api/agent/chat`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agentId: agent.id, message, conversationId }),
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        patchLast((m) => ({ ...m, content: err?.error ?? "Something went wrong. Please try again." }));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let handedOver = false;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // An event can arrive split across reads; only whole ones are parsed.
        let cut: number;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const line = raw.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          let e: any;
          try {
            e = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          if (e.type === "text") patchLast((m) => ({ ...m, content: m.content + e.content }));
          else if (e.type === "tool_call")
            patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), { id: e.id, tool: e.tool, state: "running" }] }));
          else if (e.type === "tool_result") {
            if (e.ok && e.tool === "request_human") handedOver = true;
            patchLast((m) => ({
              ...m,
              tools: (m.tools ?? []).map((t) =>
                t.id === e.id ? { ...t, state: !e.ok ? "failed" : e.held ? "held" : "ok" } : t,
              ),
            }));
          }
          else if (e.type === "blocked")
            patchLast((m) => ({ ...m, content: e.replacement ?? e.reason, notice: e.stage === "input" ? undefined : e.reason }));
          else if (e.type === "error") patchLast((m) => ({ ...m, content: m.content || e.message }));
          else if (e.type === "handoff") setHandoff({ ref: e.ref, status: e.status });
          else if (e.type === "done") {
            setConversationId(e.conversationId);
            // With a person, the assistant stays quiet: no empty bubble left behind.
            setMsgs((p) => {
              const l = p[p.length - 1];
              return l && l.role === "assistant" && !l.content && !(l.tools?.length) ? p.slice(0, -1) : p;
            });
            // The assistant just handed over (the tool ran and worked): ask where it stands.
            if (handedOver) refreshHandoff(e.conversationId);
          }
        }
      }
    } catch {
      patchLast((m) => ({ ...m, content: m.content || "I couldn't reach the assistant. Please try again." }));
    } finally {
      setBusy(false);
    }
  }

  if (!agent) return null;
  const ui = agent.ui;
  const side = ui.position === "bottom-left" ? "left-6" : "right-6";

  const panel = (
    <div
      role="dialog"
      aria-label={ui.title}
      style={{ background: C.card, color: C.text, borderColor: C.border, borderRadius: RADIUS }}
      className={
        variant === "page"
          ? "flex h-full min-h-[480px] flex-col overflow-hidden border text-sm shadow-sm"
          : `fixed bottom-6 ${side} z-50 flex h-[560px] max-h-[80vh] w-[380px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden border text-sm shadow-2xl`
      }
    >
      <div className="flex items-center justify-between px-4 py-3" style={{ background: C.primary, color: C.onPrimary }}>
        <div className="min-w-0">
          <div className="truncate text-base font-semibold" style={{ fontFamily: HEADING }}>{ui.title}</div>
          {ui.subtitle && <div className="truncate text-xs opacity-80">{ui.subtitle}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {conversationId && (
            <button
              type="button"
              onClick={newChat}
              disabled={busy}
              className="rounded px-2 py-1 text-xs hover:bg-white/20 disabled:opacity-50"
            >
              New chat
            </button>
          )}
          {variant === "floating" && (
            <button type="button" onClick={() => setOpen(false)} aria-label="Close" className="rounded p-1 hover:bg-white/20">
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3" aria-live="polite">
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                "max-w-[85%] rounded-2xl px-3 py-2 " + (m.role === "user" ? "whitespace-pre-wrap" : "")
              }
              style={
                m.role === "user"
                  ? { background: C.primary, color: C.onPrimary }
                  : m.role === "human"
                    ? { background: C.card, color: C.text, border: `1px solid ${C.primary}` }
                    : { background: C.muted, color: C.text }
              }
            >
              {m.role === "human" && (
                <div className="mb-0.5 text-[11px] font-medium" style={{ color: C.primary }}>
                  {handoff?.assignedToName ?? "Team member"}
                </div>
              )}
              {m.tools && m.tools.length > 0 && (
                <div className="mb-1 flex flex-wrap gap-1">
                  {m.tools.map((t) => (
                    <span key={t.id} className="rounded-full px-2 py-0.5 text-[11px]" style={{ background: C.border, color: C.mutedText }}>
                      {t.state === "running" ? "…" : t.state === "ok" ? "✓" : t.state === "held" ? "⏸" : "✗"} {label(t.tool)}
                      {t.state === "held" ? ": waiting for your OK" : ""}
                    </span>
                  ))}
                </div>
              )}
              {m.role === "user" ? m.content : m.content ? <Markdown text={m.content} /> : busy && i === msgs.length - 1 ? "…" : ""}
              {m.notice && <div className="mt-1 text-[11px] opacity-70">{m.notice}</div>}
            </div>
          </div>
        ))}
        {msgs.length <= 1 && (ui.suggestedQuestions?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-2">
            {ui.suggestedQuestions!.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => send(q)}
                className="rounded-full border px-3 py-1 text-xs hover:opacity-80"
                style={{ borderColor: C.border, color: C.text }}
              >
                {q}
              </button>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {handoff && (
        <div
          role="status"
          className="border-t px-3 py-1.5 text-xs"
          style={{ borderColor: C.border, background: C.muted, color: C.text }}
        >
          {handoff.status === "resolved"
            ? `A person resolved this (${handoff.ref})${handoff.resolutionNote ? `: ${handoff.resolutionNote}` : ""}. You are back with the assistant.`
            : handoff.status === "claimed"
              ? `${handoff.assignedToName ?? "Someone on the team"} is looking at this (${handoff.ref}).`
              : `Escalated to the team (${handoff.ref}). A person will contact you shortly: their reply will appear right here, and the bell at the top of the page will tell you too.`}
        </div>
      )}

      <form
        className="flex items-center gap-2 border-t px-3 py-2"
        style={{ borderColor: C.border }}
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything…"
          aria-label="Message"
          disabled={busy}
          className="min-w-0 flex-1 rounded-lg border bg-transparent px-3 py-2 outline-none focus:ring-2"
          style={{ borderColor: C.border, color: C.text }}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-lg px-3 py-2 font-medium disabled:opacity-50"
          style={{ background: C.primary, color: C.onPrimary }}
        >
          Send
        </button>
      </form>
    </div>
  );

  if (variant === "page") return panel;
  return open ? (
    panel
  ) : (
    <button
      type="button"
      onClick={() => setOpen(true)}
      aria-label={`Open ${ui.title}`}
      className={`fixed bottom-6 ${side} z-50 flex h-14 w-14 items-center justify-center rounded-full text-2xl shadow-lg transition-transform hover:scale-105`}
      style={{ background: C.primary, color: C.onPrimary }}
    >
      💬
    </button>
  );
}

export default ChatWidget;
