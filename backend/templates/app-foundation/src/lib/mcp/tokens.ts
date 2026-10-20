/**
 * A person's tokens for connecting an assistant to this app.
 *
 * A token stands for the person who made it: an assistant holding it can do
 * what that person can, and nothing else. Only its SHA-256 digest is kept,
 * with the last four characters to tell tokens apart, so a copy of the
 * database lets nobody in. Revoked tokens stay, marked, so the list says what
 * was turned off and when.
 *
 * `_forge_mcp_tokens` is the platform's table, declared in
 * `db/schema/_forge_mcp_tokens.ts` so the schema push keeps it, and made here
 * on first use in the same shape, for a database the push has not reached.
 *
 * Platform file: every app carries it and the platform replaces it.
 */
import { createHash, randomBytes } from "crypto";
import { sql } from "drizzle-orm";
import { db } from "@/db";

export const PREFIX = "fmcp_";

let ready = false;
async function ensure(): Promise<void> {
  if (ready) return;
  await db.execute(sql.raw(`CREATE TABLE IF NOT EXISTS _forge_mcp_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL,
    label text NOT NULL DEFAULT '',
    token_hash text NOT NULL CONSTRAINT _forge_mcp_tokens_token_hash_unique UNIQUE,
    last4 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at timestamptz)`));
  ready = true;
}

const rowsOf = (res: any): any[] => (res?.rows ?? res ?? []) as any[];
export const digest = (token: string) => createHash("sha256").update(token).digest("hex");

export type TokenRow = { id: string; label: string; last4: string; createdAt: string; lastUsedAt: string | null; revokedAt: string | null };

export async function createToken(userId: string, label: string): Promise<{ token: string; row: TokenRow }> {
  await ensure();
  const token = PREFIX + randomBytes(32).toString("base64url");
  const res = await db.execute(sql`INSERT INTO _forge_mcp_tokens (user_id, label, token_hash, last4)
    VALUES (${userId}, ${label.slice(0, 80)}, ${digest(token)}, ${token.slice(-4)})
    RETURNING id, label, last4, created_at, last_used_at, revoked_at`);
  return { token, row: shape(rowsOf(res)[0]) };
}

export async function listTokens(userId: string): Promise<TokenRow[]> {
  await ensure();
  const res = await db.execute(sql`SELECT id, label, last4, created_at, last_used_at, revoked_at
    FROM _forge_mcp_tokens WHERE user_id = ${userId} ORDER BY created_at DESC`);
  return rowsOf(res).map(shape);
}

export async function revokeToken(userId: string, id: string): Promise<boolean> {
  await ensure();
  const res = await db.execute(sql`UPDATE _forge_mcp_tokens SET revoked_at = now()
    WHERE id::text = ${id} AND user_id = ${userId} AND revoked_at IS NULL RETURNING id`);
  return rowsOf(res).length > 0;
}

/** The person a token stands for, or null — and when it was last used. */
export async function personOf(token: string): Promise<string | null> {
  if (!token.startsWith(PREFIX)) return null;
  await ensure();
  const res = await db.execute(sql`UPDATE _forge_mcp_tokens SET last_used_at = now()
    WHERE token_hash = ${digest(token)} AND revoked_at IS NULL RETURNING user_id`);
  return rowsOf(res)[0]?.user_id ?? null;
}

function shape(r: any): TokenRow {
  const iso = (v: unknown) => (v ? new Date(v as string).toISOString() : null);
  return { id: String(r.id), label: String(r.label ?? ""), last4: String(r.last4 ?? ""),
           createdAt: iso(r.created_at) ?? "", lastUsedAt: iso(r.last_used_at), revokedAt: iso(r.revoked_at) };
}
