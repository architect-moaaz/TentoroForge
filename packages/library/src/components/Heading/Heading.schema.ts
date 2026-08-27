import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * Heading props — softened for MCP-derived schemas.
 *
 * `content` was required (z.string().min(1)) with .strict() on the object.
 * MCP-derived schemas may emit extra keys (className, _figmaNodeId) that
 * failed the strict check. The object is now non-strict and content has a
 * fallback default so partial inputs render instead of "⚠ invalid props".
 *
 * className + style allow MCP-emitted Tailwind classes / inline CSS to pass
 * through the registry's strip step.
 */
export const HeadingProps = z.object({
  level:     z.number().int().min(1).max(6).default(2),
  content:   z.string().default(""),
  id:        z.string().optional(),
  weight:    z.enum(["light", "regular", "bold", "display"]).optional(),
  style:     StyleSlot.optional(),
  className: z.string().optional(),
});

export type HeadingPropsType = z.infer<typeof HeadingProps>;
