/**
 * GET /api/mews/stays?q=<confirmation number, last name or room>[&property=<id, enterprise id or name>]
 *
 * The stays Mews finds for a search, each with its guest, room and charged
 * payment (`findStays`). Anyone signed in to an application that declares Mews
 * may search: a desk starting a refund is not its administrator. Read-only;
 * nothing is kept until the person picks a stay. Forge runtime — do not remove.
 */
import { findStays } from "@/lib/mews";
import { failed, json, mewsUser } from "../guard";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request): Promise<Response> {
  const who = await mewsUser();
  if (!who.ok) return who.response;
  const url = new URL(req.url);
  const q = (url.searchParams.get("q") || "").trim();
  if (!q) return json({ stays: [] });
  try {
    return json({ stays: await findStays(q, url.searchParams.get("property") || undefined) });
  } catch (err) {
    return failed(err);
  }
}
