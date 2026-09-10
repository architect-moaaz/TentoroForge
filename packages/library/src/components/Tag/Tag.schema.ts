import { z } from "zod";
export const TagProps = z.object({
  label:     z.string().default("Tag"),
  // "accent" is implemented by VARIANT_CLASS in Tag.tsx (second brand hue) —
  // it was previously unreachable because it was missing from this enum.
  // Same fix as Badge.variant.
  variant:   z.enum(["default", "primary", "accent", "success", "warning", "danger"]).optional(),
  removable: z.boolean().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TagPropsType = z.infer<typeof TagProps>;
