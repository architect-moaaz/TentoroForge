/**
 * POST /api/mcp — this application as an MCP server.
 *
 * An assistant connects here with a person's token (made on /connect-ai) and
 * may then do what that person may: run the processes their role can start
 * and read the records their role can see. Each tool calls the same route a
 * screen calls, signed in as the person (`lib/mcp/session`), so the launch
 * gate, the access table, the rules and the trail all apply unchanged.
 *
 * Off unless the owner turned it on (`FORGE_APP_MCP=on`): then this answers
 * 404, as if it were not here.
 *
 * Platform file: every app carries it and the platform replaces it.
 */
import { NextResponse } from "next/server";
import catalogJson from "@/lib/mcp/catalog.json";
import { handle, type Catalog, type Doors } from "@/lib/mcp/protocol";
import { personOf } from "@/lib/mcp/tokens";
import { signIn } from "@/lib/mcp/session";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

const BASE = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
const on = () => process.env.FORGE_APP_MCP === "on";
const off = () => NextResponse.json({ error: "Not found" }, { status: 404 });

function unauthorised(message: string) {
  return NextResponse.json({ jsonrpc: "2.0", id: null, error: { code: -32001, message } },
    { status: 401, headers: { "WWW-Authenticate": 'Bearer realm="mcp", error="invalid_token"' } });
}

async function answer(res: Response): Promise<{ status: number; body: unknown }> {
  const text = await res.text();
  try { return { status: res.status, body: JSON.parse(text) }; } catch { return { status: res.status, body: text }; }
}

export async function POST(request: Request) {
  if (!on()) return off();
  const bearer = (request.headers.get("authorization") ?? "").match(/^Bearer\s+(\S+)$/i)?.[1] ?? "";
  if (!bearer) return unauthorised("Connect with a token from this app's “Connect an AI assistant” page.");
  const userId = await personOf(bearer);
  if (!userId) return unauthorised("This token is not valid, or it was revoked.");
  const signed = await signIn(userId);
  if (!signed) return unauthorised("The person this token belongs to can no longer sign in.");

  const origin = new URL(request.url).origin;
  const headers = { cookie: signed.cookie, "content-type": "application/json", accept: "application/json" };
  const doors: Doors = {
    run: async (id, input) => answer(await fetch(`${origin}${BASE}/api/workflows/${encodeURIComponent(id)}/execute`,
      { method: "POST", headers, body: JSON.stringify({ input }), cache: "no-store" })),
    read: async (slug, id, query) => {
      const qs = new URLSearchParams(query).toString();
      const path = `${BASE}/api/data/${encodeURIComponent(slug)}${id ? `/${encodeURIComponent(id)}` : ""}${qs ? `?${qs}` : ""}`;
      return answer(await fetch(`${origin}${path}`, { headers, cache: "no-store" }));
    },
  };

  let body: any;
  try { body = await request.json(); } catch {
    return NextResponse.json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }, { status: 400 });
  }
  const catalog = catalogJson as unknown as Catalog;
  const batch = Array.isArray(body);
  const replies = (await Promise.all((batch ? body : [body]).map((m: any) => handle(m, catalog, signed.person, doors))))
    .filter(Boolean);
  if (!replies.length) return new NextResponse(null, { status: 202 });
  return NextResponse.json(batch ? replies : replies[0]);
}

/** No server-sent stream: every reply comes back on its POST. */
export async function GET() {
  if (!on()) return off();
  return new NextResponse(null, { status: 405, headers: { Allow: "POST" } });
}

export async function DELETE() {
  if (!on()) return off();
  return new NextResponse(null, { status: 405, headers: { Allow: "POST" } });
}
