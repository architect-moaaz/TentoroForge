// PLACEHOLDER of the generated `src/config.generated.ts` — not copied into apps.
// What the Blueprint says about the application that the fixed half needs:
// its name, currency, languages, where a signed-in person lands, which routes
// need no sign-in, and the entity each login IS (the web's `lib/account.ts`).

export const APP_NAME: string = "Sample app";

/** ISO 4217 — what a money field is in when a record carries none (the web's `CURRENCY`). */
export const CURRENCY: string = "USD";

/** BCP-47 — how numbers and dates are written. */
export const LOCALE: string = "en-US";

/** The languages the interface offers; `dir` is "rtl" for right-to-left scripts. */
export const LANGUAGES: readonly { tag: string; dir: "ltr" | "rtl" }[] = [{ tag: "en", dir: "ltr" }];

/** The language every text falls back to. */
export const PRIMARY: string = "en";

/** Where a signed-in person lands: a route of the app. */
export const HOME: string = "/";

/** Routes (and their sub-routes) a signed-out visitor may open: public pages.
 *  Empty: everything needs a sign-in. */
export const PUBLIC_ROUTES: readonly string[] = [];

/** The entity each login IS, and what signup asks for it; null when none. */
export const ACCOUNT: null | {
  entity: string;
  fields: { name: string; label: string; kind: string; required: boolean; options?: { label: string; value: string }[] }[];
  labelField: string | null;
  locationField: string | null;
} = null;
