/**
 * Which of the platform's features this organisation may use.
 *
 * Everything is on unless it takes an app's source code out of the platform;
 * the super admin opens or shuts a feature per organisation from the cockpit.
 * A feature that is off stays visible — locked, with a note saying who can
 * open it — and the API refuses it with 403 and an `X-Forge-Feature` header.
 */
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

export type FeatureKey =
  | "drafts_room" | "discover" | "templates" | "portal" | "brand"
  | "code_view" | "legacy_editors" | "agents" | "office" | "monitoring"
  | "publish" | "mobile_builds" | "code_export"
  | "integrations" | "mcp_servers";

export type FeatureGroup = "build" | "workspace" | "ship" | "integrations";

export interface FeatureState {
  key: FeatureKey;
  name: string;
  description: string;
  group: FeatureGroup;
  default_on: boolean;
  source_out: boolean;
  enforced: "api" | "ui";
  enabled: boolean;
  source: "default" | "platform" | "org";
}

export type FeatureMap = Partial<Record<FeatureKey, FeatureState>>;

export const featuresKey = (orgId: string) => ["org", orgId, "features"] as const;

/** The note shown on a locked feature. */
export function lockedNote(name: string): string {
  return `${name} is not enabled for your organisation. Ask the platform administrator.`;
}

/** Whether `key` may be used, given what the organisation's features say.
 *  Unknown (not loaded, or a key the platform does not list) reads as open,
 *  so a slow network never locks a screen that is actually on; the API is
 *  the door that refuses. */
export function allowed(features: FeatureMap | undefined, key: FeatureKey): boolean {
  const f = features?.[key];
  return f ? f.enabled : true;
}

/** A 403 from a feature's door, as the API phrases it. */
export function isFeatureRefusal(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403 && /is not enabled for your organisation/.test(err.message);
}

export function useOrgFeatures(orgId: string | undefined) {
  const q = useQuery({
    queryKey: featuresKey(orgId || ""),
    queryFn: () => api.get<{ org_id: string; features: FeatureMap }>(`/api/orgs/${orgId}/features`),
    enabled: !!orgId,
    staleTime: 60_000,
    retry: false,
  });
  const features = q.data?.features;
  return {
    features,
    isLoading: q.isLoading,
    allowed: (key: FeatureKey) => allowed(features, key),
    nameOf: (key: FeatureKey) => features?.[key]?.name ?? key,
  };
}
