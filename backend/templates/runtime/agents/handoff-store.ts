/**
 * Handoffs on the app's own database: the store the runtime writes to, the people and notification
 * lookups, optional email, and what the inbox reads and changes. Forge runtime — do not remove.
 *
 * Every function here assumes the handoff table may not exist yet (an app updated but not yet migrated):
 * callers treat a failure as "nothing handed over", never as a reason to fail a chat.
 */
import { randomUUID } from "node:crypto";
import { db } from "@/db";
import { forgeAgentHandoffs } from "@/db/schema/_forge_agent_handoffs";
import { forgeAgentConversations, forgeAgentMessages } from "@/db/schema/_forge_agent";
import { forgeNotifications } from "@/db/schema/_forge_notifications";
import { and, asc, count, desc, eq, inArray, ne, sql } from "drizzle-orm";
import type { HandoffDeps, HandoffRecord, HandoffStatus, HandoffStore, Person, StoredMessage } from "./types";

const toRecord = (r: any): HandoffRecord => ({
  id: r.id,
  ref: r.ref,
  conversationId: r.conversationId,
  agentId: r.agentId,
  requestedById: r.requestedById,
  requestedByName: r.requestedByName,
  reason: r.reason,
  urgency: r.urgency === "urgent" || r.urgency === "low" ? r.urgency : "normal",
  contact: r.contact,
  summary: r.summary,
  status: r.status === "claimed" || r.status === "resolved" ? r.status : "open",
  assignedToId: r.assignedToId,
  assignedToName: r.assignedToName,
  resolutionNote: r.resolutionNote,
  createdAt: r.createdAt,
  claimedAt: r.claimedAt,
  resolvedAt: r.resolvedAt,
});

export const handoffStore: HandoffStore = {
  async create(h) {
    const ref = "HO-" + randomUUID().replace(/-/g, "").slice(0, 6).toUpperCase();
    // Who asked, by name, so the inbox does not show an id. Best-effort: users tables differ app to app.
    let requestedByName = h.requestedByName ?? null;
    if (!requestedByName) {
      try {
        const res: any = await (db as any).execute(sql`SELECT * FROM users WHERE id::text = ${h.requestedById} LIMIT 1`);
        const u = (Array.isArray(res) ? res : (res?.rows ?? []))[0];
        requestedByName = u ? (u.display_name ?? u.name ?? u.full_name ?? u.email ?? null) : null;
      } catch {
        /* the name is a nicety */
      }
    }
    const [row] = await db
      .insert(forgeAgentHandoffs)
      .values({ ref, ...h, requestedByName, claimedAt: null, resolvedAt: null })
      .returning();
    return toRecord(row);
  },

  async openFor(conversationId) {
    const rows = await db
      .select()
      .from(forgeAgentHandoffs)
      .where(and(eq(forgeAgentHandoffs.conversationId, conversationId), ne(forgeAgentHandoffs.status, "resolved")))
      .orderBy(desc(forgeAgentHandoffs.createdAt))
      .limit(1);
    return rows[0] ? toRecord(rows[0]) : null;
  },

  async openCounts(userIds) {
    if (!userIds.length) return {};
    const rows = await db
      .select({ id: forgeAgentHandoffs.assignedToId, n: count() })
      .from(forgeAgentHandoffs)
      .where(and(inArray(forgeAgentHandoffs.assignedToId, userIds), ne(forgeAgentHandoffs.status, "resolved")))
      .groupBy(forgeAgentHandoffs.assignedToId);
    return Object.fromEntries(rows.map((r: any) => [String(r.id), Number(r.n)]));
  },
};

// ── who, and how they are told ────────────────────────────────────────────

/** People who hold any of these roles, from the app's own users table. Column names differ app to app. */
async function people(roles: string[]): Promise<Person[]> {
  if (!roles.length) return [];
  const wanted = roles.map((r) => r.toLowerCase());
  const res: any = await (db as any).execute(sql`SELECT * FROM users LIMIT 500`);
  const rows: any[] = Array.isArray(res) ? res : (res?.rows ?? []);
  return rows
    .filter((r) => r.role && wanted.includes(String(r.role).toLowerCase()) && r.is_active !== false)
    .map((r) => ({
      id: String(r.id),
      name: r.display_name ?? r.name ?? r.full_name ?? r.email ?? null,
      email: r.email ?? null,
      role: r.role,
    }));
}

async function notify(n: { title: string; message: string; userId?: string | null; role?: string | null; entityId?: string }) {
  await db.insert(forgeNotifications).values({
    title: n.title,
    message: n.message,
    userId: n.userId ?? null,
    role: n.role ?? null,
    type: "handoff",
    entityId: n.entityId ?? null,
  });
}

/** Email only when the app has a way to send it. Not having one is the normal answer, not an error. */
async function email(to: string, subject: string, body: string): Promise<{ sent: boolean; reason?: string }> {
  const { getSecret } = await import("@/lib/integrations/resolver");
  const configured = (await getSecret("smtp", "SMTP_HOST")) || (await getSecret("resend", "RESEND_API_KEY"));
  if (!configured) return { sent: false, reason: "email is not set up" };
  try {
    const { initializeRuntime } = await import("@/lib/runtime-loader");
    await initializeRuntime(); // registers the send_email action
  } catch {
    /* the handler below is then simply absent */
  }
  const engine: any = await import("@/lib/workflows/engine");
  const handler = engine.getActionHandler?.("send_email");
  if (!handler) return { sent: false, reason: "email is not set up" };
  const r: any = await handler({ to, subject, body }, { input: {}, variables: {}, log: [], user: undefined });
  return r?.sent === true ? { sent: true } : { sent: false, reason: String(r?.notice ?? "the email was not sent") };
}

/** The last few messages, as plain text, for whoever takes the handoff. */
async function snapshot(conversationId: string): Promise<string> {
  const rows = await db
    .select()
    .from(forgeAgentMessages)
    .where(eq(forgeAgentMessages.conversationId, conversationId))
    .orderBy(desc(forgeAgentMessages.createdAt))
    .limit(8);
  return rows
    .reverse()
    .map((m: any) => `${m.role === "assistant" ? "Assistant" : "Customer"}: ${String(m.content).slice(0, 300)}`)
    .join("\n");
}

export function handoffDeps(): HandoffDeps {
  return { store: handoffStore, people, notify, email, snapshot };
}

// ── the inbox ─────────────────────────────────────────────────────────────

const RANK = sql`CASE ${forgeAgentHandoffs.urgency} WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END`;

/** Unresolved first (urgent, then oldest), then the recently resolved. */
export async function listHandoffs(opts: { status?: HandoffStatus | "active" | "all"; limit?: number } = {}): Promise<HandoffRecord[]> {
  const status = opts.status ?? "active";
  const where =
    status === "all" ? undefined : status === "active" ? ne(forgeAgentHandoffs.status, "resolved") : eq(forgeAgentHandoffs.status, status);
  const q = db.select().from(forgeAgentHandoffs);
  const rows = await (where ? q.where(where) : q)
    .orderBy(status === "resolved" || status === "all" ? desc(forgeAgentHandoffs.createdAt) : asc(RANK), asc(forgeAgentHandoffs.createdAt))
    .limit(opts.limit ?? 100);
  return rows.map(toRecord);
}

export async function getHandoff(id: string): Promise<HandoffRecord | null> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) return null;
  const rows = await db.select().from(forgeAgentHandoffs).where(eq(forgeAgentHandoffs.id, id)).limit(1);
  return rows[0] ? toRecord(rows[0]) : null;
}

/** The person's own handoff for one of their conversations (any status, newest). */
export async function handoffForConversation(conversationId: string): Promise<HandoffRecord | null> {
  const rows = await db
    .select()
    .from(forgeAgentHandoffs)
    .where(eq(forgeAgentHandoffs.conversationId, conversationId))
    .orderBy(desc(forgeAgentHandoffs.createdAt))
    .limit(1);
  return rows[0] ? toRecord(rows[0]) : null;
}

/** A conversation's messages for whoever HANDLES it (the person's own reads go through store.ts). */
export async function transcript(conversationId: string): Promise<StoredMessage[]> {
  const rows = await db
    .select()
    .from(forgeAgentMessages)
    .where(eq(forgeAgentMessages.conversationId, conversationId))
    .orderBy(asc(forgeAgentMessages.createdAt));
  return rows.map((r: any) => ({
    role: r.role === "assistant" ? "assistant" : r.role === "human" ? "human" : "user",
    content: r.content,
    createdAt: r.createdAt,
  }));
}

/** A person on the team writes into the conversation. It lands where the assistant's messages do, so the person who
 *  asked sees it in their own chat. */
export async function sendReply(h: HandoffRecord, text: string): Promise<void> {
  await db.insert(forgeAgentMessages).values({ conversationId: h.conversationId, role: "human", content: text });
  await db.update(forgeAgentConversations).set({ updatedAt: new Date() }).where(eq(forgeAgentConversations.id, h.conversationId));
}

/** One bell notification, unless the same person already has an unread one of this kind for this handoff:
 *  a back-and-forth must not bury anyone in alerts. */
async function ring(userId: string, kind: "handoff" | "handoff_reply", h: HandoffRecord, title: string, message: string) {
  const unread = await db
    .select({ id: forgeNotifications.id })
    .from(forgeNotifications)
    .where(
      and(
        eq(forgeNotifications.userId, userId),
        eq(forgeNotifications.type, kind),
        eq(forgeNotifications.entityId, h.id),
        eq(forgeNotifications.read, false),
        sql`${forgeNotifications.title} LIKE 'New message%'`,
      ),
    )
    .limit(1);
  if (unread.length) return;
  await db.insert(forgeNotifications).values({ title, message, userId, type: kind, entityId: h.id });
}

/** The person wrote while a team member has the conversation: ring that team member. Best-effort. */
export async function customerWrote(h: HandoffRecord, text: string): Promise<void> {
  if (h.status !== "claimed" || !h.assignedToId) return;
  await ring(
    h.assignedToId,
    "handoff",
    h,
    `New message from ${h.requestedByName ?? "the customer"} (${h.ref})`,
    text.slice(0, 200),
  );
}

/** A team member wrote: ring the person who asked, in case their chat is closed. Best-effort. */
export async function teamWrote(h: HandoffRecord, text: string): Promise<void> {
  await ring(
    h.requestedById,
    "handoff_reply",
    h,
    `New message from ${h.assignedToName ?? "the team"} (${h.ref})`,
    text.slice(0, 200),
  );
}

export type HandoffAction =
  | { action: "claim"; by: { id: string; name?: string | null } }
  | { action: "release" }
  | { action: "resolve"; note?: string }
  | { action: "assign"; to: { id: string; name?: string | null } };

/** Move a handoff along. Returns the new record, or null when it does not exist or the move is not allowed. */
export async function changeHandoff(id: string, change: HandoffAction): Promise<HandoffRecord | null> {
  const current = await getHandoff(id);
  if (!current) return null;
  const now = new Date();
  let patch: Record<string, unknown>;
  switch (change.action) {
    case "claim":
      if (current.status === "resolved") return null;
      patch = { status: "claimed", assignedToId: change.by.id, assignedToName: change.by.name ?? null, claimedAt: now };
      break;
    case "release":
      if (current.status === "resolved") return null;
      patch = { status: "open", assignedToId: null, assignedToName: null, claimedAt: null };
      break;
    case "assign":
      if (current.status === "resolved") return null;
      patch = { assignedToId: change.to.id, assignedToName: change.to.name ?? null };
      break;
    case "resolve":
      patch = { status: "resolved", resolutionNote: (change.note ?? "").trim().slice(0, 1000) || null, resolvedAt: now };
      break;
  }
  await db.update(forgeAgentHandoffs).set(patch).where(eq(forgeAgentHandoffs.id, id));
  return getHandoff(id);
}
