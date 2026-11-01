/**
 * GET /api/agent/insights?days=7&agent=<id> — what the app's assistants cost and how they are doing: turns, tokens by
 * day and by model, speed, which tools run and fail, thumbs up and down, hand-overs, and the few conversations that
 * went wrong. Worked out from the turns the chat recorded (agents/insights.ts).
 *
 *   days    1 to 90 (7 when left out or not a number).
 *   agent   one agent's id; everyone's when left out.
 *
 * Shut exactly like /api/agent/debug: the app must not be in production, the platform's secret file
 * `.forge-debug-secret` must exist in the app folder, and the request must carry that secret. Anything else is a plain
 * 404, as if the route did not exist. The report holds counts and timings; the only words in it are a short piece of
 * what the person wrote, for the conversations that went wrong. Forge runtime — do not remove.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { sameSecret } from "@/lib/agents/debug";
import { fetchInsights } from "@/lib/agents/insights";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NOT_FOUND = () => Response.json({ error: "Not found." }, { status: 404 });

/** `null` when the request may use this; otherwise the response to give. */
async function refuse(req: Request): Promise<Response | null> {
  if (process.env.NODE_ENV === "production") return NOT_FOUND();
  let secret = "";
  try {
    secret = (await readFile(path.join(process.cwd(), ".forge-debug-secret"), "utf8")).trim();
  } catch {
    return NOT_FOUND();
  }
  return sameSecret(secret, req.headers.get("x-forge-debug-secret") ?? "") ? null : NOT_FOUND();
}

export async function GET(req: Request): Promise<Response> {
  const no = await refuse(req);
  if (no) return no;
  const url = new URL(req.url);
  try {
    return Response.json(await fetchInsights({ days: url.searchParams.get("days"), agentId: url.searchParams.get("agent") }));
  } catch (err) {
    console.error("[api/agent/insights]", err);
    return Response.json({ error: "Could not work out the insights." }, { status: 500 });
  }
}
