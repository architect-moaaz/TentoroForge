/**
 * Which of the application's gateways a payer is sent to — by the currency
 * they pay in and, when the request says, the country they are in. The
 * domestic gateway of the payer's country wins; then a gateway for paying in
 * that country's own currency; then one for international payers; then any
 * that takes the currency (the default first). The same rule Settings →
 * Payments previews (`frontend/src/lib/payment-gateways.ts`).
 *
 * A subscription stays on the gateway it began on: a mandate and a saved card
 * cannot move between gateways, so routing is only for a new payment.
 */
export interface GatewayRef {
  id: string;
  provider: string;
  label: string;
  coverage: "domestic" | "international" | "both";
  homeCountry?: string | null;
  currencies: string[];
  /** The integration slug its webhook answers under (`/api/webhooks/<slug>`). */
  integration: string;
  isDefault?: boolean;
}

/** The currency payers in a country use, for the countries Forge apps sell in. */
export const COUNTRY_CURRENCY: Record<string, string> = {
  IN: "INR", AE: "AED", SA: "SAR", QA: "QAR", KW: "KWD", BH: "BHD", OM: "OMR", US: "USD", GB: "GBP", SG: "SGD", AU: "AUD",
  CA: "CAD", JP: "JPY", MY: "MYR", ZA: "ZAR", NZ: "NZD", CH: "CHF", DE: "EUR", FR: "EUR", NL: "EUR", IE: "EUR", ES: "EUR",
  IT: "EUR", BE: "EUR", AT: "EUR", PT: "EUR", FI: "EUR", GR: "EUR", LU: "EUR",
};

export function routeFor<T extends GatewayRef>(gateways: T[], currency: string, country?: string | null): T | null {
  const cur = String(currency || "").toUpperCase();
  const where = country ? String(country).toUpperCase() : "";
  const takes = gateways.filter((g) => (g.currencies ?? []).map((c) => c.toUpperCase()).includes(cur));
  if (!takes.length) return null;
  const byDefault = (a: T, b: T) => Number(Boolean(b.isDefault)) - Number(Boolean(a.isDefault));
  if (where) {
    const home = takes.filter((g) => g.coverage !== "international" && String(g.homeCountry ?? "").toUpperCase() === where).sort(byDefault);
    if (home.length) return home[0];
  }
  if (!where) {
    const local = takes.filter((g) => g.coverage !== "international" && COUNTRY_CURRENCY[String(g.homeCountry ?? "").toUpperCase()] === cur).sort(byDefault);
    if (local.length) return local[0];
  }
  const abroad = takes.filter((g) => g.coverage !== "domestic").sort(byDefault);
  if (abroad.length) return abroad[0];
  return [...takes].sort(byDefault)[0];
}

/** The currency a payer should see first: their country's when a price exists in it, else the app's own. */
export function currencyFor(available: string[], appCurrency: string, country?: string | null): string {
  const mine = country ? COUNTRY_CURRENCY[String(country).toUpperCase()] : undefined;
  const list = available.map((c) => c.toUpperCase());
  if (mine && list.includes(mine)) return mine;
  if (list.includes(appCurrency.toUpperCase())) return appCurrency.toUpperCase();
  return list[0] ?? appCurrency.toUpperCase();
}

/** The payer's country as the platform in front of the app says it (Vercel), or null. */
export function countryOf(headers: Headers | null | undefined): string | null {
  const c = headers?.get("x-vercel-ip-country") ?? headers?.get("cf-ipcountry") ?? "";
  return /^[A-Za-z]{2}$/.test(c) ? c.toUpperCase() : null;
}
