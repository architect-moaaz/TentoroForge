import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * Button props — softened for MCP-derived schemas.
 *
 * MCP-derived schemas (Figma → PageV2) may emit only `label` without
 * aria-label/icon, or emit extra keys like `className` and `_figmaNodeId`.
 * The schema is now non-strict and the label/aria-label superRefine is removed
 * so partial inputs render with fallbacks instead of "⚠ invalid props".
 *
 * className + style passthrough are critical: without them the registry's
 * strict-parse step strips those fields before the component receives them.
 */
// shadcn — and most LLMs trained on shadcn examples — emit `variant: "default"`
// for the filled brand-colour button. We map it to `"primary"` so dispatch
// doesn't reject the prop with "⚠ Button: invalid props". Same for `"link"`
// (shadcn ghost-without-border) which we collapse to `"ghost"`.
const _variantAlias = z.preprocess(
  (v) => v === "default" ? "primary" : v === "link" ? "ghost" : v,
  z.enum(["primary", "secondary", "accent", "danger", "ghost"]),
);

export const ButtonProps = z.object({
  label:        z.string().optional(),
  variant:      _variantAlias.default("primary"),
  size:         z.enum(["sm", "md", "lg"]).default("md"),
  disabled:     z.boolean().optional(),
  loading:      z.boolean().optional(),
  workflow:     z.string().optional(),
  args:         z.record(z.unknown()).optional(),
  /** Render as a native submit button so it triggers the enclosing Form's
   *  onSubmit (which collects field values + dispatches the form's workflow). */
  submit:       z.boolean().optional(),
  navigate:     z.string().optional(),
  opensDialog:  z.string().optional(),
  /** onClick may be a NavActionDescriptor from the schema renderer. */
  onClick:      z.unknown().optional(),
  style:        StyleSlot.optional(),
  icon:         z.string().optional(),
  iconSrc:      z.string().optional(),
  iconPosition: z.enum(["left", "right"]).default("left"),
  /** When true, the rendered <button> emits `data-sidebar-toggle=""` and
   *  becomes the hamburger trigger for the app shell's mobile sidebar
   *  drawer. The ShellStateProvider's delegated click handler picks it up
   *  and toggles `isSidebarOpen`. Set automatically by the page-shell
   *  heuristic on buttons it recognises as the toggle. */
  togglesSidebar: z.boolean().optional(),
  /** When true, clicking clears every filter param from the URL and asks the
   *  host app to re-resolve the page's dataSources. This is the "Reset all
   *  filters" affordance on a filtered list/dashboard — declarative so the
   *  editor can toggle it and the emitter never has to author a handler. */
  clearsFilters: z.boolean().optional(),

  "aria-label": z.string().optional(),
  className:    z.string().optional(),
  /** Stable identifier for the journey verifier's Playwright driver.
   *  When set, the rendered <button> emits `data-journey="<slug>"` — the
   *  driver's locator resolver prefers this over role+label, so a page
   *  emitter can pin CTAs even if the label text drifts. Emitters SHOULD
   *  stamp this on the primary submit/create button. */
  dataJourney:  z.string().optional(),
});

export type ButtonPropsType = z.infer<typeof ButtonProps>;
