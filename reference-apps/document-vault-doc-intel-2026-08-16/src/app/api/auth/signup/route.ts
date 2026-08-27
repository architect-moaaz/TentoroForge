import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";
import { z } from "zod";

const signupSchema = z.object({
  name: z.string().min(1, "Name is required"),
  email: z.string().email("Invalid email"),
  password: z.string().min(6, "Password must be at least 6 characters"),
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
