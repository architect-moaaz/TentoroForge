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
function accountValues(input: Record<string, unknown>, email: string): { values?: Record<string, unknown>; error?: string } {
  if (!ACCOUNT) return {};
  // WHERE A NEW ACCOUNT STARTS. The form asks only what a person types, so
  // the state a process owns — a verification that has not happened yet — is
  // written here rather than asked for. Anything the person did fill wins.
  const values: Record<string, unknown> = { ...ACCOUNT_INITIAL };
  for (const f of ACCOUNT.fields) {
    let v = input[f.name];
    if ((v === undefined || v === "") && f.kind === "email") v = email;
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

    const account = accountValues(data.account ?? {}, data.email);
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
        await tx.insert(accountTable).values({ ...account.values, id: created.id });
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
