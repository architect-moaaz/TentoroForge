/**
 * GET /api/mews/stays/suggest?q=<part of a name or email, a confirmation number, a room>[&property=…]
 *
 * Stays to suggest while a desk types (`suggestStays`): from the stays the
 * application keeps, newest first, with who is in the hotel now from Mews.
 * Anyone signed in to an application that declares Mews. Forge runtime — do not remove.
 */
import { suggestStays } from "@/lib/mews";
import { failed, json, mewsUser } from "../../guard";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const who = await mewsUser();
  if (!who.ok) return who.response;
  const url = new URL(req.url);
  try {
    return json(await suggestStays(url.searchParams.get("q") || "", url.searchParams.get("property") || undefined));
  } catch (err) {
    return failed(err);
  }
}
