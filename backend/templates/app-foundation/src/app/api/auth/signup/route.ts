import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { policy as signInPolicy } from "@/lib/sign-in";
import { eq } from "drizzle-orm";
import { z } from "zod";
import * as accountModule from "@/lib/account";
import { SIGNUP_ROLE } from "@/lib/account";
import { accountValues, writeAccountRow } from "@/lib/account-row";

// The account types signup offers. Empty by default (single-account app);
// the Blueprint assembly step overwrites this line with the derived options
// when the app models a self-service account-type choice (e.g. crew member vs
// vessel owner). Keep the shape `{ value }[]` — assembly replaces the whole
// literal, and the empty default keeps single-account apps unchanged.
const ACCOUNT_TYPES: { value: string }[] = [];
const ACCOUNT_TYPE_VALUES = ACCOUNT_TYPES.map((t) => t.value);
/** Every role a person may give themselves (`security.signupRoles`). An app
 *  projected before the list existed has none, and only SIGNUP_ROLE is given. */
const SIGNUP_ROLES: string[] =
  ((accountModule as unknown as { SIGNUP_ROLES?: string[] }).SIGNUP_ROLES) ?? [];

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
    // ONLY A ROLE THE APP OFFERS. With no choice offered the schema let any
    // `accountType` through, and a stranger could post "Admin" and hold it
    // (DITANS, 2026-10-31): a role named here must be one signup offers.
    const offered = [...ACCOUNT_TYPE_VALUES, ...SIGNUP_ROLES];
    const chosen = data.accountType && offered.includes(data.accountType) ? data.accountType : undefined;
    const role = chosen || SIGNUP_ROLE || undefined;

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
          // The address is proved by a code before the account reaches anything.
          ...("emailVerification" in (users as any) && signInPolicy().verifyEmail ? { emailVerification: "pending" } : {}),
        } as any)
        .returning();
      await writeAccountRow(tx, created.id, account.values);
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
