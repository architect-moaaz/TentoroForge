/**
 * The company profile an organisation carries — types and calls.
 *
 * One module for both places it is used: the onboarding wizard a person meets
 * once, and the Settings tab they come back to. A second copy of these shapes
 * beside one of them is a second copy that drifts.
 */
import { api } from "@/lib/api";

// Same resolution rule as `lib/api`: `""` means same-origin, so only
// `undefined` may fall back to the dev backend.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

export type BrandStatus =
  | "pending"
  | "extracting"
  | "ready"
  | "failed"
  | "skipped";

/**
 * The three discovery answers and what was read around them. Loosely typed on
 * purpose: the backend caps and cleans these fields, and a front end that
 * declares them `required` would break the moment the interview grows one.
 */
export interface BrandIdentity {
  who_you_are?: string;
  what_you_do?: string;
  how_you_do_it?: string;
  industry?: string;
  audience?: string;
  tone?: string;
  voice?: string;
  values?: string;
  source?: string;
}

export interface BrandDesign {
  colors?: Record<string, string>;
  typography?: Record<string, string>;
  radius?: Record<string, string>;
  elevation?: Record<string, string>;
  informationDensity?: string;
  logo?: { file: string; alt?: string; mediaType?: string };
}

export interface BrandProfile {
  status: BrandStatus;
  source_url: string | null;
  company_name: string | null;
  failure_reason: string | null;
  identity: BrandIdentity;
  design: BrandDesign;
  evidence: Record<string, unknown>;
  design_md: string;
  /** Whether a build can actually be offered this. `ready` and empty is not. */
  usable: boolean;
  has_logo: boolean;
}

/** The three questions, in the order they are asked and shown. */
export const DISCOVERY_QUESTIONS: {
  key: keyof BrandIdentity;
  label: string;
  hint: string;
}[] = [
  {
    key: "who_you_are",
    label: "Who you are",
    hint: "The kind of organisation this is, and what it exists to do.",
  },
  {
    key: "what_you_do",
    label: "What you do",
    hint: "The product or service, in your own words for your own things.",
  },
  {
    key: "how_you_do_it",
    label: "How you do it",
    hint: "How you work, and what makes your way of doing it different.",
  },
];

/**
 * The colour roles shown in the editor, in the order they matter. Roles the
 * discovery did not fill are still offered — an empty one is a thing the
 * person can supply, not a thing to hide from them.
 */
export const COLOR_ROLES: { key: string; label: string }[] = [
  { key: "primary", label: "Brand" },
  { key: "accent", label: "Accent" },
  { key: "background", label: "Page" },
  { key: "foreground", label: "Text" },
  { key: "border", label: "Lines" },
];

export const brand = {
  get: (orgId: string) => api.get<BrandProfile | null>(`/api/orgs/${orgId}/brand`),
  discover: (orgId: string, url: string) =>
    api.post<BrandProfile>(`/api/orgs/${orgId}/brand/discover`, { url }),
  update: (
    orgId: string,
    body: {
      company_name?: string;
      identity?: BrandIdentity;
      design?: BrandDesign;
    },
  ) => api.put<BrandProfile>(`/api/orgs/${orgId}/brand`, body),
  skip: (orgId: string) => api.post<BrandProfile>(`/api/orgs/${orgId}/brand/skip`),

  /**
   * The mark, as a blob URL an `<img>` can actually show.
   *
   * NOT a plain URL into the API. `/brand/logo` is behind `get_current_user`
   * like every other org route, and an `<img src>` cannot carry an
   * Authorization header — pointing one at the endpoint renders a broken
   * image on every page that shows the logo, which is exactly what it did.
   * Putting the token in the query string instead would fix the picture by
   * writing a credential into a URL that ends up in logs and referrers.
   *
   * So the bytes are fetched the way every other authenticated request is,
   * and handed to the element as an object URL. Callers must revoke it when
   * the element goes away; `useBrandLogo` does.
   */
  logoObjectUrl: async (orgId: string): Promise<string | null> => {
    const token =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (!token) return null;
    try {
      const res = await fetch(
        `${API_BASE}/api/orgs/${orgId}/brand/logo`,
        { headers: { Authorization: `Bearer ${token}` }, credentials: "include" },
      );
      if (!res.ok) return null;
      return URL.createObjectURL(await res.blob());
    } catch {
      // A company with no readable mark still has a design language, and a
      // missing picture must never take the screen down with it.
      return null;
    }
  },
};

/** A one-line description of what was read, for a card or a toast. */
export function describeDesign(design: BrandDesign): string {
  const parts: string[] = [];
  const primary = design.colors?.primary;
  if (primary) parts.push(primary);
  const family =
    design.typography?.fontFamilyHeading || design.typography?.fontFamilyBase;
  if (family) parts.push(`set in ${family}`);
  if (design.informationDensity) parts.push(design.informationDensity);
  return parts.join(" · ");
}

/**
 * `acme.com` / `https://www.acme.co.uk/about` → `Acme`.
 *
 * Used to name the workspace BEFORE discovery has run, because a profile
 * belongs to an organisation and the organisation has to exist to hold it.
 * Replaced by the real name the moment the read comes back — this is a
 * placeholder with a short life, not a guess anybody has to live with.
 */
export function companyNameFromUrl(raw: string): string {
  const trimmed = raw.trim().replace(/^https?:\/\//i, "").replace(/^www\./i, "");
  const host = trimmed.split("/")[0] || trimmed;
  const label = host.split(".")[0] || "workspace";
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function slugFromName(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "workspace"
  );
}
