import { z } from "zod";
const Img = z.object({ src: z.string(), alt: z.string().optional() });
export const LightboxProps = z.object({
  images:    z.array(Img).default([]),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type LightboxPropsType = z.infer<typeof LightboxProps>;
