import { z } from "zod";
export const RedirectProps = z.object({
  /** Destination route, e.g. "/documents/upload". */
  to:        z.string(),
  /** Optional one-line note shown while the redirect fires. */
  label:     z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type RedirectPropsType = z.infer<typeof RedirectProps>;
