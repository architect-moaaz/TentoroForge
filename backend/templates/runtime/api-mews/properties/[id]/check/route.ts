/**
 * POST /api/mews/properties/:id/check — ask Mews who the property is
 * (configuration/get) with its own credentials, and keep the answer.
 *
 * The administrator's alone (`../../../../guard`). Forge runtime — do not remove.
 */
import { checkProperty } from "@/lib/mews";
import { failed, json, mewsAdmin } from "../../../guard";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> | { id: string } };

export async function POST(_req: Request, ctx: Params): Promise<Response> {
  const who = await mewsAdmin();
  if (!who.ok) return who.response;
  const { id } = await ctx.params;
  try {
    return json({ property: await checkProperty(id) });
  } catch (err) {
    return failed(err);
  }
}
