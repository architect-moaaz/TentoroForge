/**
 * PATCH  /api/mews/properties/:id — change a property. `accessToken` replaces
 *        the token; null removes it; left out (or sent back as its mask) keeps it.
 * DELETE /api/mews/properties/:id — remove the property and its token.
 *
 * The administrator's alone (`../../../guard`). Forge runtime — do not remove.
 */
import { removeProperty, updateProperty } from "@/lib/mews";
import { failed, json, mewsAdmin, readJson } from "../../guard";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> | { id: string } };

export async function PATCH(req: Request, ctx: Params): Promise<Response> {
  const who = await mewsAdmin();
  if (!who.ok) return who.response;
  const { id } = await ctx.params;
  try {
    return json({ property: await updateProperty(id, await readJson(req)) });
  } catch (err) {
    return failed(err);
  }
}

export async function DELETE(_req: Request, ctx: Params): Promise<Response> {
  const who = await mewsAdmin();
  if (!who.ok) return who.response;
  const { id } = await ctx.params;
  try {
    return (await removeProperty(id)) ? json({ removed: id }) : json({ error: "No such property." }, 404);
  } catch (err) {
    return failed(err);
  }
}
