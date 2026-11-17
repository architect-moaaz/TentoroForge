import * as SecureStore from 'expo-secure-store';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { apiJson } from './api';
import { useSession } from './session';

export interface OrgInfo {
  id: string;
  name: string;
  slug: string;
}

interface FeatureState {
  enabled: boolean;
  name?: string;
}

interface OrgContext {
  orgs: OrgInfo[];
  /** The organisation the person is working in. Null until loaded. */
  org: OrgInfo | null;
  setOrgId: (id: string) => void;
  loading: boolean;
  error: string | null;
  reload: () => void;
  /** True when a platform admin has switched this feature off for the org. */
  isLocked: (feature?: string) => boolean;
  featureName: (feature: string) => string;
}

const Ctx = createContext<OrgContext | null>(null);
const ORG_KEY = 'org_id';

export function OrgProvider({ children }: { children: ReactNode }) {
  const { status } = useSession();
  const [orgs, setOrgs] = useState<OrgInfo[]>([]);
  const [orgId, setOrgIdState] = useState<string | null>(null);
  const [features, setFeatures] = useState<Record<string, FeatureState>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await apiJson<OrgInfo[]>('/api/orgs');
      const saved = await SecureStore.getItemAsync(ORG_KEY).catch(() => null);
      setOrgs(list);
      setOrgIdState(list.find((o) => o.id === saved)?.id ?? list[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load your organisations');
    } finally {
      setLoading(false);
    }
  }, []);

  // Load when someone signs in; forget everything when they sign out.
  useEffect(() => {
    if (status === 'in') {
      load();
    } else {
      setOrgs([]);
      setOrgIdState(null);
      setFeatures({});
    }
  }, [status, load]);

  useEffect(() => {
    if (!orgId) return;
    let alive = true;
    apiJson<{ features?: Record<string, FeatureState> }>(`/api/orgs/${orgId}/features`)
      .then((body) => alive && setFeatures(body.features ?? {}))
      // A failed lookup must not lock people out: unknown reads as allowed.
      .catch(() => alive && setFeatures({}));
    return () => {
      alive = false;
    };
  }, [orgId]);

  const setOrgId = useCallback((id: string) => {
    setOrgIdState(id);
    SecureStore.setItemAsync(ORG_KEY, id).catch(() => {});
  }, []);

  const value = useMemo<OrgContext>(
    () => ({
      orgs,
      org: orgs.find((o) => o.id === orgId) ?? null,
      setOrgId,
      loading,
      error,
      reload: load,
      isLocked: (feature) => (feature ? features[feature]?.enabled === false : false),
      featureName: (feature) => features[feature]?.name ?? feature,
    }),
    [orgs, orgId, setOrgId, loading, error, load, features],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useOrg(): OrgContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useOrg must be used inside OrgProvider');
  return ctx;
}
