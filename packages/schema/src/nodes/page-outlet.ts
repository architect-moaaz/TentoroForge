import { z } from "zod";

/**
 * PageOutlet — a structural placeholder that the shell renderer replaces with
 * the current route's rendered content. Use this node in shell.json to mark
 * where the page body should appear (below the top nav, inside the main area,
 * etc.). The renderer resolves it via PageOutletContext at render time.
 *
 * PageOutlet has no static children and no props — it's a pure mount-point.
 */
export const PageOutletNode = z
  .object({
    id: z.string().optional(),
    type: z.literal("PageOutlet"),
    props: z.object({}).optional(),
    children: z.array(z.never()).optional(),
  })
  .strict();

export type PageOutletNodeT = z.infer<typeof PageOutletNode>;
