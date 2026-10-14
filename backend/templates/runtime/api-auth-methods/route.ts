/**
 * GET /api/auth/methods — how a person may sign in here: password, a magic
 * link, and each identity provider with whether it is CONNECTED in this
 * environment (its names set). The form offers what is connected and says
 * what is declared but not; nothing here is a secret, only names and booleans.
 *
 * Forge runtime — do not remove.
 */
import { methods } from "@/lib/sign-in";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json(methods());
}
