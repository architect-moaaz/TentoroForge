import { NextRequest, NextResponse } from "next/server";

/**
 * POST /api/figma/extract
 *
 * Forwards to FastAPI's /agents/figma-extract endpoint.
 * Body: { fileKey: string, nodeId: string }
 *
 * Used by the editor's "Import from Figma" modal (Cmd+Shift+F).
 */
export async function POST(req: NextRequest) {
  const body = await req.json();
  const url = `${process.env.FASTAPI_URL ?? "http://localhost:6500"}/agents/figma-extract`;
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return NextResponse.json(await r.json(), { status: r.status });
  } catch (e: any) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
