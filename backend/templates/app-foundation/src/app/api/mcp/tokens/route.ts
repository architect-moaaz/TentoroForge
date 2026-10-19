/**
 * The signed-in person's tokens for connecting an assistant: list, make, revoke.
 * A token's value is shown once, when it is made; only its digest is kept.
 *
 * Platform file: every app carries it and the platform replaces it.
 */
import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { createToken, listTokens, revokeToken } from "@/lib/mcp/tokens";

export const dynamic = "force-dynamic";

const on = () => process.env.FORGE_APP_MCP === "on";

async function person(): Promise<string | null> {
  const session = await auth();
  const id = (session?.user as { id?: string } | undefined)?.id;
  return id ? String(id) : null;
}

export async function GET() {
  if (!on()) return NextResponse.json({ enabled: false }, { status: 404 });
  const id = await person();
  if (!id) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  return NextResponse.json({ enabled: true, path: "/api/mcp", tokens: await listTokens(id) });
}

export async function POST(request: Request) {
  if (!on()) return NextResponse.json({ enabled: false }, { status: 404 });
  const id = await person();
  if (!id) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const body = await request.json().catch(() => ({}));
  const label = String(body?.label ?? "").trim() || "AI assistant";
  const made = await createToken(id, label);
  return NextResponse.json({ token: made.token, row: made.row });
}

export async function DELETE(request: Request) {
  if (!on()) return NextResponse.json({ enabled: false }, { status: 404 });
  const id = await person();
  if (!id) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const tokenId = new URL(request.url).searchParams.get("id") ?? "";
  return NextResponse.json({ revoked: tokenId ? await revokeToken(id, tokenId) : false });
}
