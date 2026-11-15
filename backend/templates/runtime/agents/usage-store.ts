/**
 * The usage counts on the app's own database: one row per person per minute. Forge runtime — do not remove.
 *
 * Callers treat any failure here (typically: the table does not exist yet in an app that was updated but not
 * migrated) as "not limited", never as a reason to refuse a message.
 */
import { db } from "@/db";
import { forgeAgentUsage } from "@/db/schema/_forge_agent_usage";
import { and, eq, gt, lt, sql } from "drizzle-orm";
import type { Usage, UsageStore } from "./limits";

const MINUTE = 60_000;

export const usageStore: UsageStore = {
  async read(userId): Promise<Usage> {
    const now = Date.now();
    const thisMinute = Math.floor(now / MINUTE) * MINUTE;
    const rows = await db
      .select({ bucket: forgeAgentUsage.bucket, messages: forgeAgentUsage.messages, tokens: forgeAgentUsage.tokens })
      .from(forgeAgentUsage)
      .where(and(eq(forgeAgentUsage.userId, userId), gt(forgeAgentUsage.bucket, new Date(now - 24 * 60 * MINUTE))));
    const used: Usage = { minute: 0, hour: 0, tokensDay: 0 };
    for (const r of rows) {
      const at = new Date(r.bucket).getTime();
      used.tokensDay += Number(r.tokens) || 0;
      if (at > now - 60 * MINUTE) used.hour += Number(r.messages) || 0;
      if (at === thisMinute) used.minute += Number(r.messages) || 0;
    }
    return used;
  },

  async add(userId, delta) {
    const bucket = new Date(Math.floor(Date.now() / MINUTE) * MINUTE);
    const messages = delta.messages ?? 0;
    const tokens = delta.tokens ?? 0;
    await db
      .insert(forgeAgentUsage)
      .values({ userId, bucket, messages, tokens })
      .onConflictDoUpdate({
        target: [forgeAgentUsage.userId, forgeAgentUsage.bucket],
        set: { messages: sql`${forgeAgentUsage.messages} + ${messages}`, tokens: sql`${forgeAgentUsage.tokens} + ${tokens}` },
      });
    // Rows older than two days are of no use to any limit: tidy them up now and then.
    if (Math.random() < 0.02) {
      await db.delete(forgeAgentUsage).where(lt(forgeAgentUsage.bucket, new Date(Date.now() - 48 * 60 * MINUTE))).catch(() => {});
    }
  },
};
