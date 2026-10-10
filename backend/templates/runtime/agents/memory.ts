/**
 * Agent memory — what the model is told of the conversation so far.
 * Forge runtime — do not remove.
 *
 * Pure helpers over a `ConversationStore`; the drizzle-backed store lives in
 * store.ts so these can be exercised with an in-memory one.
 */
import type { ConfirmState, ConversationStore, MemorySpec, ModelMessage, StoredMessage } from "./types";

/**
 * How many of the most recent assistant turns are replayed WITH what their tools returned.
 * Older turns are words only: the facts they fetched have probably moved on, and the context
 * is finite.
 */
export const REPLAY_TOOL_TURNS = 3;
/** One tool result is cut to this many characters, so a long list cannot fill the context. */
export const MAX_RESULT_CHARS = 3000;

function clip(text: string): string {
  return text.length > MAX_RESULT_CHARS
    ? `${text.slice(0, MAX_RESULT_CHARS)}… [cut: ${text.length - MAX_RESULT_CHARS} more characters]`
    : text;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/**
 * An assistant turn that used tools, as the model lived it: the calls it made, what they
 * returned, then what it said. Without this the model saw only its own words and looked
 * the same record up again on every follow-up ("change that customer" -> fetch the customer).
 * The results are what the tool runner returned, so credentials are already redacted.
 */
function withToolResults(m: StoredMessage, at: number): ModelMessage[] {
  const calls = m.toolCalls ?? [];
  const uses = calls.map((c, k) => ({
    type: "tool_use" as const,
    id: `toolu_replay_${at}_${k}`,
    name: c.name,
    input: asRecord(c.input),
  }));
  const results = calls.map((c, k) => ({
    type: "tool_result" as const,
    tool_use_id: uses[k].id,
    content: c.error ? `Error: ${c.error}` : clip(JSON.stringify(c.result ?? null)),
    ...(c.error ? { is_error: true } : {}),
  }));
  return [
    { role: "assistant", content: uses },
    { role: "user", content: results },
    { role: "assistant", content: m.content || "Done." },
  ];
}

/**
 * The replay the model sees: the rolling summary (if any) then the most recent turns, the
 * last few with what their tools returned. `toolNames` are the tools the agent has NOW; a
 * turn that used a tool since removed is replayed as words only, never as a call the model
 * can no longer make.
 */
export async function loadHistory(
  store: ConversationStore,
  conversationId: string,
  summary: string | null,
  spec: MemorySpec,
  toolNames?: ReadonlySet<string>,
): Promise<ModelMessage[]> {
  const rows = await store.listMessages(conversationId);
  const recent = rows.slice(-Math.max(1, spec.maxMessages));
  // The API requires the first turn to be the user's. Dropped before anything is expanded, so a
  // turn is never cut in half (a tool result with no call before it is refused).
  let start = 0;
  while (start < recent.length && recent[start].role !== "user") start++;
  const turns = recent.slice(start);

  // The most recent assistant turns that used tools, newest first.
  const replay = new Set<number>();
  for (let i = turns.length - 1; i >= 0 && replay.size < REPLAY_TOOL_TURNS; i--) {
    const calls = turns[i].toolCalls;
    if (turns[i].role === "assistant" && calls && calls.length > 0 && (!toolNames || calls.every((c) => toolNames.has(c.name)))) {
      replay.add(i);
    }
  }

  const out: ModelMessage[] = [];
  if (summary) {
    // A summary is context, not a turn the person typed — framed as such so the
    // model does not answer it.
    out.push({ role: "user", content: `[Earlier in this conversation: ${summary}]` });
    out.push({ role: "assistant", content: "Understood." });
  }
  turns.forEach((m, i) => {
    if (replay.has(i)) out.push(...withToolResults(m, i));
    // A person on the team wrote this while the conversation was theirs: the assistant sees it as said, not as its own.
    else if (m.role === "human") out.push({ role: "assistant", content: `[A person on the team wrote: ${m.content}]` });
    else out.push({ role: m.role, content: m.content });
  });
  return out;
}

/**
 * Fold the oldest turns into the summary once the stored count passes
 * `summarizeAfter`, keeping `maxMessages` verbatim. `summarize` is the model call
 * (injected); when it fails the messages are KEPT — losing history is worse than
 * carrying a little more of it.
 */
export async function summarizeIfNeeded(
  store: ConversationStore,
  conversationId: string,
  currentSummary: string | null,
  spec: MemorySpec,
  summarize: (text: string) => Promise<string>,
): Promise<boolean> {
  const rows = await store.listMessages(conversationId);
  if (rows.length < spec.summarizeAfter) return false;
  const keep = Math.max(1, spec.maxMessages);
  const old: StoredMessage[] = rows.slice(0, Math.max(0, rows.length - keep));
  if (old.length === 0) return false;
  const transcript =
    (currentSummary ? `Earlier summary: ${currentSummary}\n\n` : "") +
    old.map((m) => `${m.role}: ${m.content}`).join("\n");
  let summary = "";
  try {
    summary = (await summarize(transcript)).trim();
  } catch {
    return false;
  }
  if (!summary) return false;
  const ids = old.map((m) => m.id).filter((x): x is string => !!x);
  await store.setSummary(conversationId, summary, ids);
  return true;
}

/** An in-memory store — used by tests, and by the platform's dry-run. */
export function memoryStore(): ConversationStore & { dump(): Record<string, StoredMessage[]> } {
  const convs = new Map<string, { id: string; agentId: string; userId: string; summary: string | null }>();
  const msgs = new Map<string, StoredMessage[]>();
  const states = new Map<string, ConfirmState>();
  let n = 0;
  return {
    async getConversation(id, userId) {
      const c = convs.get(id);
      return c && c.userId === userId ? { id: c.id, summary: c.summary } : null;
    },
    async createConversation(agentId, userId) {
      const id = `conv-${++n}`;
      convs.set(id, { id, agentId, userId, summary: null });
      msgs.set(id, []);
      return id;
    },
    async listMessages(id) {
      return [...(msgs.get(id) ?? [])];
    },
    async saveMessage(id, msg) {
      const list = msgs.get(id) ?? [];
      list.push({ ...msg, id: msg.id ?? `m-${++n}` });
      msgs.set(id, list);
    },
    async getState(id) {
      const s = states.get(id);
      return s ? { turn: s.turn, holds: [...s.holds] } : { turn: 0, holds: [] };
    },
    async setState(id, state) {
      states.set(id, { turn: state.turn, holds: [...state.holds] });
    },
    async setSummary(id, summary, drop) {
      const c = convs.get(id);
      if (c) c.summary = summary;
      msgs.set(id, (msgs.get(id) ?? []).filter((m) => !m.id || !drop.includes(m.id)));
    },
    dump() {
      return Object.fromEntries(msgs.entries());
    },
  };
}
