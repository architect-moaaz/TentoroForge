import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";
import { z } from "zod";

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

    const hashedPassword = await bcrypt.hash(data.password, 12);

    const [user] = await db
      .insert(users)
      .values({
        email: data.email,
        password: hashedPassword,
        ...("name" in (users as any) ? { name: data.name } : {}),
        ...("firstName" in (users as any) ? { firstName: data.name.split(" ")[0], lastName: data.name.split(" ").slice(1).join(" ") || "" } : {}),
        // Persist the chosen account type when the table carries the column
        // and a choice was actually offered; auth folds it into the session.
        ...("accountType" in (users as any) && data.accountType ? { accountType: data.accountType } : {}),
      } as any)
      .returning();

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
