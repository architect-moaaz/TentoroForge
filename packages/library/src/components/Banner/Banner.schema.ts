import { z } from "zod";

/** Same two exact shapes EmptyState.action uses — one union, not one object
 *  with both keys optional, because an action carrying neither is the bug the
 *  union exists to prevent. `navigate` is the library's own word for a route
 *  (Link.navigate, Button.navigate), so this spells it the same way. */
const BannerAction = z.union([
  z.object({ label: z.string().min(1), workflow: z.string().min(1) }).strict(),
  z.object({ label: z.string().min(1), navigate: z.string().min(1) }).strict(),
]);

export const BannerProps = z.object({
  variant:     z.enum(["info", "success", "warning", "error"]).default("info"),
  title:       z.string().optional(),
  message:     z.string().default(""),
  dismissible: z.boolean().optional(),
  /** Leading icon name, resolved through the shared icon registry. No default:
   *  a per-variant icon would change every banner in every shipped app. */
  icon:        z.string().optional(),
  /** The call to action a page-level notification usually needs. */
  action:      BannerAction.optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type BannerPropsType = z.infer<typeof BannerProps>;
