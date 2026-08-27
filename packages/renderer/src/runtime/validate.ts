import { Page as PageSchema } from "@tentoroforge/schema";

export function validatePage(input: unknown) {
  const result = PageSchema.safeParse(input);
  if (result.success) return result.data;
  // Advisory only: generated schemas legitimately put binding expressions
  // ("{{stats.total}}") in typed fields (resolved at runtime) and may omit
  // runtime-optional fields (e.g. layout). renderNode resolves/tolerates these,
  // so a strict-schema miss must NOT crash the page — warn and render as-is.
  const msg = result.error.errors
    .map((e) => `${e.path.join(".") || "<root>"}: ${e.message}`)
    .join("; ");
  console.warn(`[renderer] Page did not strictly validate (${msg}); rendering as-is.`);
  return input as ReturnType<typeof PageSchema.parse>;
}
