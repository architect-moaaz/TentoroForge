/** GET /api/audit/verify — walks the chain: every row's hash recomputes and links to the one before. */
import { NextResponse } from "next/server";
import { verifyChain } from "@/lib/audit";
import { reviewer } from "../route";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  const who = await reviewer();
  if (!who.ok) return NextResponse.json({ error: who.error }, { status: who.status });
  return NextResponse.json(await verifyChain());
}
