/**
 * Agent memory — what the model is told of the conversation so far.
 * Forge runtime — do not remove.
 *
 * Pure helpers over a `ConversationStore`; the drizzle-backed store lives in
 * store.ts so these can be exercised with an in-memory one.
 */
import type { ConversationStore, MemorySpec, ModelMessage, StoredMessage } from "./types";

/** The replay the model sees: the rolling summary (if any) then the most recent turns. */
export async function loadHistory(
  store: ConversationStore,
  conversationId: string,
  summary: string | null,
  spec: MemorySpec,
): Promise<ModelMessage[]> {
  const rows = await store.listMessages(conversationId);
  const recent = rows.slice(-Math.max(1, spec.maxMessages));
  const out: ModelMessage[] = [];
  if (summary) {
    // A summary is context, not a turn the person typed — framed as such so the
    // model does not answer it.
    out.push({ role: "user", content: `[Earlier in this conversation: ${summary}]` });
    out.push({ role: "assistant", content: "Understood." });
  }
  for (const m of recent) {
    out.push({ role: m.role, content: m.content });
  }
  // The API requires the first turn to be the user's.
  while (out.length && out[0].role !== "user") out.shift();
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
