import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

// Non-strict + optional icon/aria-label so the schema/Figma pipeline (which
// emits `iconSrc` for an exported SVG and per-node `className`) validates. The
// component renders `iconSrc` as an <img> when present, else the `icon` glyph,
// and falls back to a generic aria-label when none is supplied.
export const IconButtonProps = z.object({
  icon: z.string().optional(),
  iconSrc: z.string().optional(),
  "aria-label": z.string().optional(),
  variant: z.enum(["primary", "secondary", "danger", "ghost"]).default("secondary"),
  size: z.enum(["sm", "md", "lg"]).default("md"),
  disabled: z.boolean().optional(),
  loading: z.boolean().optional(),
  workflow: z.string().optional(),
  args: z.record(z.unknown()).optional(),
  navigate: z.string().optional(),
  className: z.string().optional(),
  style: StyleSlot.optional(),
});

export type IconButtonPropsType = z.infer<typeof IconButtonProps>;
