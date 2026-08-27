import { z } from "zod";
export const BannerProps = z.object({
  variant:     z.enum(["info", "success", "warning", "error"]).default("info"),
  title:       z.string().optional(),
  message:     z.string().default(""),
  dismissible: z.boolean().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type BannerPropsType = z.infer<typeof BannerProps>;
