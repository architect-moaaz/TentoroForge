import { z } from "zod";

/**
 * Softened Checkbox props for the library component.
 *
 * The canonical CheckboxNode requires `name` and `label` (z.string().min(1)).
 * MCP-derived schemas omit both, so we make them optional with defaults so
 * partial inputs render instead of showing "⚠ invalid props".
 *
 * className + style allow MCP-emitted Tailwind classes / inline CSS to
 * pass through the registry's strict-parse step unchanged.
 */
export const CheckboxProps = z.object({
  name:      z.string().default("checkbox"),
  label:     z.string().optional(),
  bind:      z.string().optional(),
  validators: z.object({
    required: z.boolean().optional(),
    min:      z.number().optional(),
    max:      z.number().optional(),
    pattern:  z.string().optional(),
    message:  z.string().optional(),
  }).optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});

export type CheckboxPropsType = z.infer<typeof CheckboxProps>;
