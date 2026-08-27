import { z } from "zod";

/**
 * Softened Input props for the library component.
 *
 * The canonical InputNode in @tentoroforge/schema requires `name` and `label`
 * (z.string().min(1)), which is correct for LLM-emitted schemas that always
 * include them. MCP-derived schemas (Figma → PageV2) typically omit those
 * fields, so we make them optional with sensible defaults here so partial
 * inputs render with placeholder/label fallbacks instead of "⚠ invalid props".
 *
 * className + style are explicitly allowed so MCP-emitted Tailwind classes and
 * inline CSS objects are not stripped by the registry's strict-parse step.
 */
export const InputProps = z.object({
  name:        z.string().default("field"),
  label:       z.string().optional(),
  type:        z.enum(["text", "email", "password", "number", "url", "tel"]).default("text"),
  placeholder: z.string().optional(),
  bind:        z.string().optional(),
  validators:  z.object({
    required: z.boolean().optional(),
    min:      z.number().optional(),
    max:      z.number().optional(),
    pattern:  z.string().optional(),
    message:  z.string().optional(),
  }).optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
  /** Lucide icon name rendered inside the field, leading edge.
   *  e.g. `search` for a search input, `mail` for an email field. */
  iconLeft:    z.string().optional(),
  /** Lucide icon name rendered inside the field, trailing edge.
   *  e.g. `eye` for a password reveal, `chevron-down` for a select-like cue. */
  iconRight:   z.string().optional(),
});

export type InputPropsType = z.infer<typeof InputProps>;
