/**
 * THE PERSON'S OWN RECORD, WITH THE LOGIN — for every way an account is made.
 *
 * When the application has an account entity, a new login gets its row too,
 * with the same id, so `$user.id` IS the person's row everywhere. Signing up
 * with a password made it; signing up through an identity provider did not,
 * and a professional who came in with Google held a login with no profile
 * behind it (DITANS, 2026-11-16). Both ways go through here now.
 *
 * Only the fields the entity declares are written; a required one left out is
 * refused in words.
 */
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";
import * as accountModule from "@/lib/account";
import { ACCOUNT, ACCOUNT_INITIAL } from "@/lib/account";
import { accountTable } from "@/lib/account-table";
import { sealSensitive } from "@/lib/data-engine";
import { ensureDataEngineInitialized } from "@/lib/data-init";

const NAME_LIKE = /^(display_?name|name|full_?name|user_?name|nick_?name)$/i;

/** WHOSE RECORD THE ACCOUNT ENTITY IS FIRST. The role people sign up as by
 *  default (SIGNUP_ROLE), an account type of it, or no role at all must make
 *  the record: a missing required field refuses the signup. Another role
 *  offered at signup (`security.signupRoles` — an employer, an agency) may
 *  keep its person elsewhere: it gets the record when what it sent makes one,
 *  and is never refused for the record's fields. Every recruiter sign-up on
 *  DITANS was refused "Plan is required" by the Candidate record (2026-11-17). */
export function ownsAccountRecord(role: string | null | undefined): boolean {
  const m = accountModule as unknown as { SIGNUP_ROLE?: string | null; SIGNUP_ROLES?: string[] };
  if (!role || role === m.SIGNUP_ROLE) return true;
  return !(m.SIGNUP_ROLES ?? []).includes(role);
}

export function accountValues(input: Record<string, unknown>, email: string, name = "", role?: string | null): { values?: Record<string, unknown>; error?: string } {
  if (!ACCOUNT) return {};
  const made = recordFrom(input, email, name);
  return made.error && !ownsAccountRecord(role) ? {} : made;
}

function recordFrom(input: Record<string, unknown>, email: string, name: string): { values?: Record<string, unknown>; error?: string } {
  if (!ACCOUNT) return {};
  // WHERE A NEW ACCOUNT STARTS. The form asks only what a person types, so
  // the state a process owns — a verification that has not happened yet — is
  // written here rather than asked for. Anything the person did fill wins.
  const values: Record<string, unknown> = { ...ACCOUNT_INITIAL };
  for (const f of ACCOUNT.fields) {
    let v = input[f.name];
    if ((v === undefined || v === "") && f.kind === "email") v = email;
    // THE NAME TYPED AT SIGNUP IS THE PERSON'S NAME ON THEIR RECORD. A
    // display-name field the form never sent as `account.displayName` was
    // refused as missing while the Name box held it (pcn4owv7, 2026-10-15).
    if ((v === undefined || v === "") && name && (ACCOUNT.labelField === f.name || NAME_LIKE.test(f.name))) v = name;
    // A VALUE THE APPLICATION STARTS WITH COUNTS AS SUPPLIED: it was decided
    // for the fields nobody is asked about, and "" is a decision too.
    if ((v === undefined || v === "" || v === null) && Object.prototype.hasOwnProperty.call(ACCOUNT_INITIAL, f.name)) continue;
    if (v === undefined || v === "" || v === null) {
      if (f.required) return { error: `${f.label} is required` };
      continue;
    }
    values[f.name] = f.kind === "number" ? Number(v) : f.kind === "checkbox" ? Boolean(v) : v;
  }
  return { values };
}

/** Write the account row for the login just made, inside the caller's transaction. */
export async function writeAccountRow(tx: any, loginId: unknown, values: Record<string, unknown> | undefined): Promise<void> {
  if (!ACCOUNT || !accountTable || !values) return;
  if ((accountTable as unknown) === (users as unknown)) {
    // THE PERSON'S RECORD IS THE LOGIN'S OWN ROW. An account entity on
    // the platform's `users` table (SnapIT's "User") folds into it; a
    // second insert into that table wrote a row with no password and
    // every signup failed (2026-09-29). The row just made is completed
    // with the columns the table has — a field folded into a platform
    // column (displayName → name) is already there.
    const own: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(values)) {
      if (k in (users as any) && !["id", "email", "password"].includes(k)) own[k] = v;
    }
    if (Object.keys(own).length) await tx.update(users).set(own as any).where(eq(users.id, loginId as any));
    return;
  }
  // SEALED AS IT IS WRITTEN, like every write through the engine. Left
  // in the clear, a new person's sensitive fields waited for the next
  // start's seal pass — on a deployed app, the next deploy (DITANS QA,
  // 2026-11-02). Without a key the values stay plain, as before.
  const row: Record<string, unknown> = { ...values, id: loginId };
  try {
    // The record types first: without them the engine cannot tell which
    // columns hold a seal, and leaves every value as written.
    await ensureDataEngineInitialized();
    await sealSensitive(ACCOUNT.entity, row);
  } catch (e) {
    console.warn("[signup] sensitive fields left unsealed:", String((e as Error)?.message ?? e).slice(0, 200));
  }
  await tx.insert(accountTable).values(row as any);
}
