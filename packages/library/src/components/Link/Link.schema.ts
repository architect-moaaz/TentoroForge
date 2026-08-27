import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * Link props — softened for MCP-derived schemas.
 *
 * `label` and `navigate` were previously required (z.string().min(1)).
 * MCP-derived schemas may omit `navigate` entirely (the link is purely
 * decorative from Figma), so both are now optional with safe defaults.
 *
 * className + style passthrough allow MCP-emitted Tailwind classes to
 * survive the registry's strip step.
 */
export const LinkProps = z.object({
  label:     z.string().default("Link"),
  navigate:  z.string().default("#"),
  workflow:  z.string().optional(),
  args:      z.record(z.unknown()).optional(),
  style:     StyleSlot.optional(),
  className: z.string().optional(),
});

export type LinkPropsType = z.infer<typeof LinkProps>;
