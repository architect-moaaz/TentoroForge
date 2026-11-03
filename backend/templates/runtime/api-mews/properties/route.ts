/**
 * GET  /api/mews/properties — the application's Mews properties (tokens as masks).
 * POST /api/mews/properties — add one: {name, enterpriseId?, environment?, accessToken?}.
 *
 * The administrator's alone (`../../guard`). A token goes in and never comes
 * back out. Forge runtime — do not remove.
 */
import { addProperty, listProperties } from "@/lib/mews";
import { failed, json, mewsAdmin, readJson } from "../guard";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const who = await mewsAdmin();
  if (!who.ok) return who.response;
  try {
    return json({ properties: await listProperties() });
  } catch (err) {
    return failed(err);
  }
}

export async function POST(req: Request): Promise<Response> {
  const who = await mewsAdmin();
  if (!who.ok) return who.response;
  try {
    return json({ property: await addProperty(await readJson(req), who.user.id) }, 201);
  } catch (err) {
    return failed(err);
  }
}
