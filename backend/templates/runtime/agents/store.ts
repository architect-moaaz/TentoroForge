/**
 * The conversation store, on the app's own database. Forge runtime — do not remove.
 */
import { db } from "@/db";
import { forgeAgentConversations, forgeAgentMessages } from "@/db/schema/_forge_agent";
import { and, asc, eq, inArray, sql } from "drizzle-orm";
import type { ConfirmState, ConversationStore, StoredMessage } from "./types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const drizzleStore: ConversationStore = {
  async getConversation(id, userId) {
    // An id that is not a uuid can belong to no one; asking Postgres to cast it
    // would be a 500 for what is a plain "no such conversation".
    if (!UUID.test(id)) return null;
    const rows = await db
      .select({ id: forgeAgentConversations.id, summary: forgeAgentConversations.summary })
      .from(forgeAgentConversations)
      .where(and(eq(forgeAgentConversations.id, id), eq(forgeAgentConversations.userId, userId)))
      .limit(1);
    return rows[0] ?? null;
  },

  async createConversation(agentId, userId) {
    const rows = await db
      .insert(forgeAgentConversations)
      .values({ agentId, userId })
      .returning({ id: forgeAgentConversations.id });
    return rows[0].id;
  },

  async listMessages(conversationId) {
    const rows = await db
      .select()
      .from(forgeAgentMessages)
      .where(eq(forgeAgentMessages.conversationId, conversationId))
      .orderBy(asc(forgeAgentMessages.createdAt));
    return rows.map(
      (r): StoredMessage => ({
        id: r.id,
        role: r.role === "assistant" ? "assistant" : r.role === "human" ? "human" : "user",
        content: r.content,
        toolCalls: (r.toolCalls as StoredMessage["toolCalls"]) ?? null,
        tokenCount: r.tokenCount,
        createdAt: r.createdAt,
      }),
    );
  },

  async saveMessage(conversationId, msg) {
    await db.insert(forgeAgentMessages).values({
      conversationId,
      role: msg.role,
      content: msg.content,
      toolCalls: msg.toolCalls ?? null,
      tokenCount: msg.tokenCount ?? null,
    });
    await db
      .update(forgeAgentConversations)
      .set({ updatedAt: new Date() })
      .where(eq(forgeAgentConversations.id, conversationId));
  },

  async getState(conversationId): Promise<ConfirmState> {
    const rows = await db
      .select({ metadata: forgeAgentConversations.metadata })
      .from(forgeAgentConversations)
      .where(eq(forgeAgentConversations.id, conversationId))
      .limit(1);
    const c = (rows[0]?.metadata as { confirm?: Partial<ConfirmState> } | null)?.confirm;
    return { turn: Number(c?.turn) || 0, holds: Array.isArray(c?.holds) ? c.holds : [] };
  },

  async setState(conversationId, state) {
    await db
      .update(forgeAgentConversations)
      .set({ metadata: sql`coalesce(${forgeAgentConversations.metadata}, '{}'::jsonb) || ${JSON.stringify({ confirm: state })}::jsonb` })
      .where(eq(forgeAgentConversations.id, conversationId));
  },

  async setSummary(conversationId, summary, dropMessageIds) {
    await db
      .update(forgeAgentConversations)
      .set({ summary })
      .where(eq(forgeAgentConversations.id, conversationId));
    if (dropMessageIds.length) {
      await db.delete(forgeAgentMessages).where(inArray(forgeAgentMessages.id, dropMessageIds));
    }
  },
};

/** The signed-in person's recent conversations with one agent, newest first. */
export async function listConversations(agentId: string, userId: string, limit = 30) {
  const { desc } = await import("drizzle-orm");
  return db
    .select({
      id: forgeAgentConversations.id,
      summary: forgeAgentConversations.summary,
      updatedAt: forgeAgentConversations.updatedAt,
    })
    .from(forgeAgentConversations)
    .where(and(eq(forgeAgentConversations.agentId, agentId), eq(forgeAgentConversations.userId, userId)))
    .orderBy(desc(forgeAgentConversations.updatedAt))
    .limit(limit);
}

/** One conversation's messages, if it is the person's. */
export async function readConversation(id: string, userId: string) {
  const conv = await drizzleStore.getConversation(id, userId);
  if (!conv) return null;
  return { id: conv.id, summary: conv.summary, messages: await drizzleStore.listMessages(id) };
}
