import { z } from "zod";
export const TagProps = z.object({
  label:     z.string().default("Tag"),
  variant:   z.enum(["default", "primary", "success", "warning", "danger"]).optional(),
  removable: z.boolean().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TagPropsType = z.infer<typeof TagProps>;
