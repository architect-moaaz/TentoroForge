/**
 * What each integration is for, said once: the provider names the pipeline
 * uses are internal (`expo_eas`, `apple_asc`, `paddleocr`), and a settings
 * page that shows them raw, every key as a bare input in one long column,
 * asks the person to know the platform's insides. Here each provider has a
 * name, a sentence on what it unlocks, a group, and a rule for when it counts
 * as connected.
 */

export interface CatalogEntry {
  provider: string;
  key: string;
  label: string;
  kind: "password" | "text" | "url" | "select";
  required: boolean;
  default: string | null;
  help_url: string | null;
  options: string[] | null;
  /** Used by Forge while it builds (design tools, photos, DNS) — never copied into an app. */
  platform_only?: boolean;
}

export interface IntegrationEntry extends CatalogEntry {
  is_set: boolean;
  updated_at: string | null;
}

export type GroupId = "email" | "ai" | "payments" | "systems" | "design" | "files" | "domains" | "mobile" | "platform";

export const GROUPS: ReadonlyArray<{ id: GroupId; title: string; blurb: string }> = [
  { id: "email", title: "Email", blurb: "How the apps you build send mail: invitations, reminders, notifications." },
  { id: "ai", title: "AI", blurb: "The model behind every build, and the features inside the apps that use it." },
  { id: "payments", title: "Payments", blurb: "How the apps take money, in test and for real." },
  { id: "systems", title: "Connected systems", blurb: "Outside systems the apps you build read from and write to, and the keys each one needs." },
  { id: "design", title: "Design & imagery", blurb: "Where a design is read from, and where photographs come from, while an app is built." },
  { id: "files", title: "Files & documents", blurb: "Where uploads live, and how documents are read." },
  { id: "domains", title: "Domains & DNS", blurb: "Lets Forge add the records an app's own domain needs, at your DNS provider." },
  { id: "mobile", title: "Mobile publishing", blurb: "The accounts a native build is signed with and submitted through." },
  { id: "platform", title: "Platform", blurb: "Secrets the generated apps carry for their own machinery." },
];

export interface ProviderInfo {
  name: string;
  purpose: string;
  group: GroupId;
  /** A provider managed on another page shows a link there, not inputs. */
  managedAt?: { href: string; label: string };
  /** A note shown in the card when it matters. */
  note?: string;
}

export const PROVIDERS: Record<string, ProviderInfo> = {
  resend: { name: "Resend", purpose: "Transactional email through Resend's API.", group: "email" },
  smtp: { name: "SMTP server", purpose: "Email through your own mail server. When a host is set, it is used instead of Resend.", group: "email" },
  anthropic: { name: "Anthropic", purpose: "The Claude model that builds the apps and powers their AI features.", group: "ai" },
  embeddings: { name: "Embeddings", purpose: "The service that turns images and text into vectors for similarity search in the apps.", group: "ai" },
  stripe: { name: "Stripe", purpose: "Card payments in the apps: live keys for production, test keys for the test deployment.", group: "payments" },
  unsplash: { name: "Unsplash", purpose: "Photographs for sign-in panels, hero bands and empty states, credited to their photographers.", group: "design",
              note: "Used by Forge while it builds; without a key, pages use the brand gradient." },
  cloudflare: { name: "Cloudflare", purpose: "Adds the DNS records an app's own domain needs (App settings → Domains → Add the records for me).", group: "domains",
                note: "Forge never replaces mail records, and asks before changing anything already there." },
  route53: { name: "Amazon Route 53", purpose: "Adds the DNS records an app's own domain needs in your hosted zones.", group: "domains",
             note: "Forge never replaces mail records, and asks before changing anything already there." },
  godaddy: { name: "GoDaddy", purpose: "Adds the DNS records an app's own domain needs at GoDaddy.", group: "domains",
             note: "Forge never replaces mail records, and asks before changing anything already there." },
  push: { name: "Web push", purpose: "The keys the apps use to send notifications to installed phones and browsers.", group: "platform",
          note: "Generated per app when absent; set here only to share one identity across apps." },
  mews: { name: "Mews", purpose: "The apps read and write hotels' reservations, guests and rooms in Mews. The client token is your integration's, set once here. Each hotel's access token is added by the app's administrator on the app's own Mews properties page; set one here only for a single hotel, or as a portfolio token.", group: "systems" },
  figma: { name: "Figma", purpose: "Read a Figma file so an app is built to its design.", group: "design" },
  uxpilot: { name: "UX Pilot", purpose: "Generate page designs with UX Pilot when an app is laid out.", group: "design" },
  s3: { name: "Amazon S3", purpose: "Where the apps keep files people upload.", group: "files" },
  paddleocr: { name: "PaddleOCR", purpose: "Read text out of scanned documents and photos.", group: "files" },
  expo_eas: { name: "Expo EAS", purpose: "Build the iPhone and Android app from the web app.", group: "mobile" },
  apple_asc: { name: "App Store Connect", purpose: "Sign and submit the iPhone app to the App Store.", group: "mobile" },
  google_play: { name: "Google Play", purpose: "Submit the Android app to Google Play.", group: "mobile" },
  cron: { name: "Scheduled jobs", purpose: "The secret that lets the scheduler call an app's timed jobs.", group: "platform" },
  encryption: { name: "Encryption at rest", purpose: "The key that seals sensitive columns in the apps' databases.", group: "platform",
                note: "Generated for each app when absent; set one here only to share a key across apps." },
  mcp: { name: "MCP servers", purpose: "Tools the apps' agents can call.", group: "platform",
         managedAt: { href: "/mcp-servers", label: "Manage MCP servers" } },
};

export const MODEL_LABELS: Record<string, string> = {
  "claude-opus-4-8": "Claude Opus 4.8 — most capable",
  "claude-opus-4-7": "Claude Opus 4.7",
  "claude-sonnet-5": "Claude Sonnet 5 — balanced (latest)",
  "claude-sonnet-4-6": "Claude Sonnet 4.6 — balanced",
  "claude-haiku-4-5-20251001": "Claude Haiku 4.5 — fastest",
  "claude-fable-5": "Claude Fable 5",
};

export type Status = "connected" | "partial" | "unset";

/**
 * Connected when every required key is set — or, for a provider whose keys
 * are all optional, when any is. Partly set when something is there but a
 * required key is not. Nothing set is not set up.
 */
export function statusOf(entries: IntegrationEntry[]): Status {
  const set = entries.filter((e) => e.is_set);
  if (set.length === 0) return "unset";
  const required = entries.filter((e) => e.required);
  if (required.length === 0) return "connected";
  return required.every((e) => e.is_set) ? "connected" : "partial";
}

export const STATUS_TEXT: Record<Status, string> = {
  connected: "Connected",
  partial: "Needs attention",
  unset: "Not set up",
};

/** The last time any key of the provider changed, or null. */
export function lastUpdated(entries: IntegrationEntry[]): string | null {
  const stamps = entries.map((e) => e.updated_at).filter((s): s is string => Boolean(s)).sort();
  return stamps.length ? stamps[stamps.length - 1] : null;
}

export function groupByProvider<T extends { provider: string }>(rows: T[]): Record<string, T[]> {
  const out: Record<string, T[]> = {};
  for (const r of rows) (out[r.provider] ??= []).push(r);
  return out;
}

/** The prefix of the keys an application declares for a system of its own (`app:<integration>`). */
export const APP_PROVIDER = "app:";

/**
 * Providers in the order the groups list them; one the catalogue does not know goes last, under Platform.
 * A system an application declares is named from its keys' labels ("Xero — XERO_API_KEY"), under
 * Connected systems.
 */
export function infoFor(provider: string, entries: ReadonlyArray<{ label: string }> = []): ProviderInfo {
  if (PROVIDERS[provider]) return PROVIDERS[provider];
  if (provider.startsWith(APP_PROVIDER)) {
    const named = entries.map((e) => e.label.split(" — ")[0]).find((n) => n && !n.includes("_"));
    const slug = provider.slice(APP_PROVIDER.length).replace(/[-_]+/g, " ").trim();
    return {
      name: named || slug.replace(/\b\w/g, (c) => c.toUpperCase()) || provider,
      purpose: "Keys an app you built declared for a system it calls. Each goes to the apps that declare it.",
      group: "systems",
    };
  }
  return { name: provider, purpose: "", group: "platform" };
}


/**
 * Whether a provider answers a search: its name, what it is for, its group,
 * its internal id, and every key's label and name — so "smtp", "upload",
 * "App Store" and "AWS_SECRET" all find what the person means.
 */
export function matches(provider: string, entries: ReadonlyArray<{ key: string; label: string }>, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const info = infoFor(provider, entries);
  const group = GROUPS.find((g) => g.id === info.group);
  const hay = [provider, info.name, info.purpose, group?.title ?? "", ...entries.flatMap((e) => [e.key, e.label])]
    .join(" ").toLowerCase();
  return q.split(/\s+/).every((word) => hay.includes(word));
}

/** True when every key of the provider is used by Forge while it builds and never copied into an app. */
export function platformOnly(entries: ReadonlyArray<{ platform_only?: boolean }>): boolean {
  return entries.length > 0 && entries.every((e) => e.platform_only);
}
