import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";
import { z } from "zod";
import { ACCOUNT, ACCOUNT_INITIAL, SIGNUP_ROLE } from "@/lib/account";
import { accountTable } from "@/lib/account-table";

// The account types signup offers. Empty by default (single-account app);
// the Blueprint assembly step overwrites this line with the derived options
// when the app models a self-service account-type choice (e.g. crew member vs
// vessel owner). Keep the shape `{ value }[]` — assembly replaces the whole
// literal, and the empty default keeps single-account apps unchanged.
const ACCOUNT_TYPES: { value: string }[] = [];
const ACCOUNT_TYPE_VALUES = ACCOUNT_TYPES.map((t) => t.value);

const signupSchema = z.object({
  name: z.string().min(1, "Name is required"),
  email: z.string().email("Invalid email"),
  password: z.string().min(6, "Password must be at least 6 characters"),
  // Only enforced when the app offers a choice; a lone or absent option means
  // signup never sends one and this stays undefined.
  accountType: z
    .string()
    .optional()
    .refine(
      (v) => ACCOUNT_TYPE_VALUES.length === 0 || (!!v && ACCOUNT_TYPE_VALUES.includes(v)),
      "Please choose an account type"
    ),
  // The account entity's own fields (see `@/lib/account`), checked below.
  account: z.record(z.string(), z.unknown()).optional(),
});

/**
 * THE PERSON'S OWN RECORD, WITH THE LOGIN. When the application has an
 * account entity, signup creates its row too — the same id as the login, so
 * `$user.id` IS the person's row everywhere. Only the fields the entity
 * declares are written; a required one left out is refused in words.
 */
const NAME_LIKE = /^(display_?name|name|full_?name|user_?name|nick_?name)$/i;

function accountValues(input: Record<string, unknown>, email: string, name = ""): { values?: Record<string, unknown>; error?: string } {
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

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const data = signupSchema.parse(body);

    // Check if user exists
    const [existing] = await db
      .select({ id: users.id })
      .from(users)
      .where(eq(users.email, data.email))
      .limit(1);

    if (existing) {
      return NextResponse.json(
        { error: { code: "CONFLICT", message: "Email already registered" } },
        { status: 409 }
      );
    }

    const account = accountValues(data.account ?? {}, data.email, data.name);
    if (account.error) {
      return NextResponse.json(
        { error: { code: "VALIDATION_ERROR", message: account.error } },
        { status: 400 }
      );
    }

    const hashedPassword = await bcrypt.hash(data.password, 12);
    // The role: the one chosen, else the one self-registered people get —
    // auth folds `accountType` into the session role, and without one a new
    // person held a role no page or workflow names.
    const role = data.accountType || SIGNUP_ROLE || undefined;

    // AN ORGANISATION AT SIGNUP, when the application has several and lets a
    // new person start one: the tenant row, the first membership (in the
    // signup role) and the active organisation, all in the one transaction.
    const tenancy = await import("@/lib/tenancy");
    const tpolicy = await tenancy.policy();
    const orgName = String((body as any)?.organisation?.name ?? (body as any)?.organisation ?? "").trim();
    if (tpolicy.kind === "organisation" && tpolicy.signup === "creates_organisation" && !orgName) {
      return NextResponse.json({ error: { code: "VALIDATION_ERROR", message: "Name your organisation to sign up." } }, { status: 400 });
    }
    // One transaction: never a login without its person, or the reverse.
    const user = await (db as any).transaction(async (tx: any) => {
      const [created] = await tx
        .insert(users)
        .values({
          email: data.email,
          password: hashedPassword,
          ...("name" in (users as any) ? { name: data.name } : {}),
          ...("firstName" in (users as any) ? { firstName: data.name.split(" ")[0], lastName: data.name.split(" ").slice(1).join(" ") || "" } : {}),
          ...("accountType" in (users as any) && role ? { accountType: role } : {}),
        } as any)
        .returning();
      if (ACCOUNT && accountTable && account.values) {
        if ((accountTable as unknown) === (users as unknown)) {
          // THE PERSON'S RECORD IS THE LOGIN'S OWN ROW. An account entity on
          // the platform's `users` table (SnapIT's "User") folds into it; a
          // second insert into that table wrote a row with no password and
          // every signup failed (2026-09-29). The row just made is completed
          // with the columns the table has — a field folded into a platform
          // column (displayName → name) is already there.
          const own: Record<string, unknown> = {};
          for (const [k, v] of Object.entries(account.values)) {
            if (k in (users as any) && !["id", "email", "password"].includes(k)) own[k] = v;
          }
          if (Object.keys(own).length) await tx.update(users).set(own as any).where(eq(users.id, created.id));
        } else {
          await tx.insert(accountTable).values({ ...account.values, id: created.id });
        }
      }
      if (tpolicy.kind === "organisation" && orgName && tpolicy.signup !== "joins_by_invite") {
        const orgId = await tenancy.createOrganisation(orgName);
        if (orgId) {
          await tenancy.join(String(created.id), orgId, role || tpolicy.memberRoles[0] || "member");
          await tenancy.setActive(String(created.id), orgId);
        }
      }
      return created;
    });

    return NextResponse.json(
      { id: user.id, email: user.email },
      { status: 201 }
    );
  } catch (error: any) {
    if (error?.name === "ZodError") {
      return NextResponse.json(
        { error: { code: "VALIDATION_ERROR", message: error.errors[0]?.message } },
        { status: 400 }
      );
    }
    console.error("Signup error:", error);
    return NextResponse.json(
      { error: { code: "INTERNAL_ERROR", message: "Failed to create account" } },
      { status: 500 }
    );
  }
}
