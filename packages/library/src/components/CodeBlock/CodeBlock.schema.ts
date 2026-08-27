import { z } from "zod";
export const CodeBlockProps = z.object({
  code:      z.string().default(""),
  language:  z.string().optional(),
  showCopy:  z.boolean().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type CodeBlockPropsType = z.infer<typeof CodeBlockProps>;
