// (dev-only) — excluded from production builds via next.config.mjs webpack null-loader rule.
// Phase 2E: forwards POST body to FastAPI /agents/schema-followup endpoint.
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const url = `${process.env.FASTAPI_URL ?? "http://localhost:6500"}/agents/schema-followup`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) return NextResponse.json({ suggestions: [] });
    return NextResponse.json(await r.json());
  } catch {
    return NextResponse.json({ suggestions: [] });
  }
}
