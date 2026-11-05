/**
 * Payment gateways — what Settings → Payments and the build dialog share:
 * the shapes the API answers with, the calls, and the one rule that decides
 * which gateway a payer is sent to (the same rule the generated app runs:
 * `backend/templates/runtime/payments/routing.ts`).
 *
 * Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
 */
import { api } from "@/lib/api";

export type Mode = "test" | "live";
export type Coverage = "domestic" | "international" | "both";
export type GatewayStatus = "ready" | "test_only" | "unchecked" | "attention";

export interface ProviderField {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  prefix: Partial<Record<Mode, string[]>>;
  help: string;
}

export interface ProviderInfo {
  id: string;
  name: string;
  tagline: string;
  coverage: Coverage;
  homeCountry: string | null;
  currencies: string[];
  defaultCurrencies: string[];
  testName: string;
  keysUrl: Partial<Record<Mode, string>>;
  webhooks: "auto" | "manual";
  paymentMethods: string;
  fields: ProviderField[];
}

export interface ModeCheck {
  ok?: boolean;
  reachable?: boolean;
  account?: string;
  accountId?: string;
  country?: string | null;
  currency?: string | null;
  checkedAt?: string;
  error?: string;
}

export interface Gateway {
  id: string;
  provider: string;
  providerName: string;
  label: string;
  coverage: Coverage;
  homeCountry: string | null;
  currencies: string[];
  isDefault: boolean;
  status: GatewayStatus;
  modes: Record<Mode, { set: boolean; check: ModeCheck | null; masked?: Record<string, string> }>;
  webhooks: "auto" | "manual";
  testName: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface GatewayBody {
  provider?: string;
  label?: string;
  coverage?: Coverage;
  homeCountry?: string | null;
  currencies?: string[];
  isDefault?: boolean;
  test?: Record<string, string>;
  live?: Record<string, string>;
  clear?: Mode[];
}

export const gatewaysKey = (orgId: string) => ["paymentGateways", orgId] as const;

export const gatewayApi = {
  providers: () => api.get<ProviderInfo[]>("/api/payment-gateways/providers"),
  list: (orgId: string) => api.get<{ gateways: Gateway[]; canManage: boolean }>(`/api/orgs/${orgId}/payment-gateways`),
  create: (orgId: string, body: GatewayBody) => api.post<Gateway>(`/api/orgs/${orgId}/payment-gateways`, body),
  edit: (orgId: string, id: string, body: GatewayBody) => api.patch<Gateway>(`/api/orgs/${orgId}/payment-gateways/${id}`, body),
  check: (orgId: string, id: string) => api.post<Gateway>(`/api/orgs/${orgId}/payment-gateways/${id}/check`),
  remove: (orgId: string, id: string) => api.delete<{ removed: string; apps: { id: string; name: string }[]; newDefault: { id: string; label: string } | null }>(`/api/orgs/${orgId}/payment-gateways/${id}`),
  apps: (orgId: string, id: string) => api.get<{ apps: { id: string; name: string }[] }>(`/api/orgs/${orgId}/payment-gateways/${id}/apps`),
};

/** Each gateway's mark: its initial on its brand colour. No logos are shipped. */
export const BRAND: Record<string, { bg: string; fg: string; mark: string }> = {
  razorpay: { bg: "#0C2451", fg: "#3395FF", mark: "R" },
  stripe: { bg: "#635BFF", fg: "#FFFFFF", mark: "S" },
  paypal: { bg: "#003087", fg: "#FFC439", mark: "P" },
};

export const STATUS_WORDS: Record<GatewayStatus, string> = {
  ready: "Ready for live payments",
  test_only: "Test keys only",
  unchecked: "Not checked yet",
  attention: "Needs attention",
};

/** The countries a business most often sells from, with the currency payers there use. */
export const COUNTRIES: ReadonlyArray<{ code: string; name: string; currency: string }> = [
  { code: "IN", name: "India", currency: "INR" },
  { code: "AE", name: "United Arab Emirates", currency: "AED" },
  { code: "SA", name: "Saudi Arabia", currency: "SAR" },
  { code: "QA", name: "Qatar", currency: "QAR" },
  { code: "KW", name: "Kuwait", currency: "KWD" },
  { code: "BH", name: "Bahrain", currency: "BHD" },
  { code: "OM", name: "Oman", currency: "OMR" },
  { code: "US", name: "United States", currency: "USD" },
  { code: "GB", name: "United Kingdom", currency: "GBP" },
  { code: "DE", name: "Germany", currency: "EUR" },
  { code: "FR", name: "France", currency: "EUR" },
  { code: "NL", name: "Netherlands", currency: "EUR" },
  { code: "IE", name: "Ireland", currency: "EUR" },
  { code: "SG", name: "Singapore", currency: "SGD" },
  { code: "AU", name: "Australia", currency: "AUD" },
  { code: "CA", name: "Canada", currency: "CAD" },
  { code: "JP", name: "Japan", currency: "JPY" },
  { code: "MY", name: "Malaysia", currency: "MYR" },
  { code: "ZA", name: "South Africa", currency: "ZAR" },
  { code: "NZ", name: "New Zealand", currency: "NZD" },
  { code: "CH", name: "Switzerland", currency: "CHF" },
];

export const countryName = (code: string | null | undefined) =>
  COUNTRIES.find((c) => c.code === code)?.name ?? (code || "");

export function coverageWords(g: Pick<Gateway, "coverage" | "homeCountry">): string {
  const home = countryName(g.homeCountry);
  if (g.coverage === "domestic") return home ? `Payers in ${home}` : "Domestic payers";
  if (g.coverage === "international") return home ? `Payers outside ${home}` : "Payers worldwide";
  return home ? `Payers in ${home} and abroad` : "Payers anywhere";
}

/** Which mode a pasted key belongs to, by its prefix — or null when it does not say. */
export function modeOfKey(provider: ProviderInfo | undefined, value: string): Mode | null {
  if (!provider) return null;
  for (const f of provider.fields) {
    for (const mode of ["test", "live"] as Mode[]) {
      if ((f.prefix[mode] ?? []).some((p) => value.trim().startsWith(p))) return mode;
    }
  }
  return null;
}

/** Which field (and mode) a pasted value belongs in, by its prefix: a Key ID pasted where the secret goes is found. */
export function fieldOfKey(provider: ProviderInfo | undefined, value: string): { field: ProviderField; mode: Mode } | null {
  const v = value.trim();
  if (!provider || !v) return null;
  for (const f of provider.fields) {
    for (const mode of ["test", "live"] as Mode[]) {
      if ((f.prefix[mode] ?? []).some((p) => v.startsWith(p))) return { field: f, mode };
    }
  }
  return null;
}

/** A field's value against its prefix: "" when it fits, else what is wrong. */
export function prefixProblem(field: ProviderField, mode: Mode, value: string, testName: string): string {
  const v = value.trim();
  if (!v || !field.prefix[mode]?.length) return "";
  const other: Mode = mode === "test" ? "live" : "test";
  if ((field.prefix[other] ?? []).some((p) => v.startsWith(p))) {
    return other === "live" ? "This is a live key — it goes under Live." : `This is a ${testName.toLowerCase()} key — it goes under ${testName}.`;
  }
  if (!(field.prefix[mode] ?? []).some((p) => v.startsWith(p))) return `Should start with ${(field.prefix[mode] ?? []).join(" or ")}`;
  return "";
}

type Routable = Pick<Gateway, "id" | "label" | "providerName" | "provider" | "coverage" | "homeCountry" | "currencies" | "isDefault">;

/**
 * THE ROUTING RULE — which gateway a payer is sent to, by the currency they
 * pay in and (when known) where they are. The domestic gateway of the payer's
 * country wins; then a gateway for international payers; then any that takes
 * the currency (the default first). Mirrors the app's `routing.ts`.
 */
export function routeFor<T extends Routable>(gateways: T[], currency: string, country?: string | null): T | null {
  const takes = gateways.filter((g) => g.currencies.includes(currency));
  if (takes.length === 0) return null;
  const byDefault = (a: T, b: T) => Number(b.isDefault) - Number(a.isDefault);
  if (country) {
    const home = takes.filter((g) => g.coverage !== "international" && g.homeCountry === country).sort(byDefault);
    if (home.length) return home[0];
  }
  const homeCurrency = (g: T) => COUNTRIES.find((c) => c.code === g.homeCountry)?.currency;
  // Paying in a domestic gateway's own currency, with no country known: that gateway.
  if (!country) {
    const local = takes.filter((g) => g.coverage !== "international" && homeCurrency(g) === currency).sort(byDefault);
    if (local.length) return local[0];
  }
  const abroad = takes.filter((g) => g.coverage !== "domestic").sort(byDefault);
  if (abroad.length) return abroad[0];
  return [...takes].sort(byDefault)[0];
}

/** Each currency the chosen gateways take, and who it goes to: "INR → Razorpay India". */
export function routingLines<T extends Routable>(gateways: T[]): Array<{ currency: string; gateway: T }> {
  const currencies = Array.from(new Set(gateways.flatMap((g) => g.currencies)));
  return currencies.map((currency) => ({ currency, gateway: routeFor(gateways, currency)! })).filter((l) => l.gateway);
}

/** The best gateways to tick for a new app: the default, and a domestic + an international pair when both exist. */
export function suggested<T extends Routable & { status?: GatewayStatus }>(gateways: T[], appCurrency?: string | null): T[] {
  const usable = gateways.filter((g) => g.status !== "attention");
  if (!usable.length) return [];
  const pick: T[] = [];
  // One account per provider: an app cannot take money through two Stripe accounts.
  const add = (g?: T) => { if (g && !pick.some((p) => p.provider === g.provider)) pick.push(g); };
  if (appCurrency) add(routeFor(usable, appCurrency) ?? undefined);
  add(usable.find((g) => g.isDefault));
  const domestic = usable.find((g) => g.coverage === "domestic");
  const international = usable.find((g) => g.coverage !== "domestic" && g.provider !== domestic?.provider);
  if (pick.some((g) => g.coverage === "domestic")) add(international);
  else if (pick.some((g) => g.coverage !== "domestic") && domestic) add(domestic);
  return pick;
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
