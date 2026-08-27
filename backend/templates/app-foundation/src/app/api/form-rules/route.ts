import { NextResponse } from "next/server";

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

    const { evaluateFormRules } = await import("@/lib/rules");
    const result = await evaluateFormRules(model, values, body?.user);
    return NextResponse.json({
      patches: result.patches ?? {},
      formHints: result.formHints ?? [],
    });
  } catch {
    // Rules engine unavailable / bad input — no hints, form unchanged.
    return NextResponse.json({ patches: {}, formHints: [] });
  }
}
