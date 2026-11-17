import { NextResponse } from "next/server";
import { auth } from "@/auth";

// Evaluates the FORM-side business rules for a model against the current form
// values and returns the field hints (hidden/required/readonly/recommendation)
// and any set/default/compute patches. The client form calls this (debounced)
// so visibility/required/lock react to what the user types. Rule logic stays
// server-side (where rules/index.json is readable). Fail-safe: any error returns
// empty hints so the form behaves exactly as if no rules existed.
export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => ({}));
    const model = typeof body?.model === "string" ? body.model : "";
    const values =
      body?.values && typeof body.values === "object" ? body.values : {};
    if (!model) return NextResponse.json({ patches: {}, formHints: [] });
    // An edit form says which record it edits and how it was loaded: rules
    // about a change ("a rejected one stays rejected", "only on create") are
    // then asked as a change. Only hints — the save checks the stored record.
    const id = typeof body?.id === "string" || typeof body?.id === "number" ? body.id : undefined;
    const previous =
      body?.previous && typeof body.previous === "object" && !Array.isArray(body.previous) ? body.previous : null;

    const { evaluateFormRules } = await import("@/lib/rules");
    // The person is the SERVER session, never a `user` the form wrote into the
    // body: a rule that reads `user.role` must see the role the caller has, or a
    // hint (a field shown, a value filled) is one anybody could ask for as anyone.
    const session = await auth();
    const user = session?.user ?? undefined;
    const result = await evaluateFormRules(model, id !== undefined ? { ...values, id } : values, user, previous);
    return NextResponse.json({
      patches: result.patches ?? {},
      formHints: result.formHints ?? [],
      // What a save of these values would be refused for, said while typing.
      errors: (result as { errors?: string[] }).errors ?? [],
    });
  } catch {
    // Rules engine unavailable / bad input — no hints, form unchanged.
    return NextResponse.json({ patches: {}, formHints: [] });
  }
}
