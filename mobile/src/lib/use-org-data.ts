import { useCallback, useEffect, useState } from 'react';

import { useOrg } from './org';

/** Loads data for the current organisation on mount and on pull-to-refresh.
 *  `fetcher` gets the org id; `loading` is true only for the first load. */
export function useOrgData<T>(fetcher: (orgId: string) => Promise<T>) {
  const { org } = useOrg();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    setError(null);
    try {
      setData(await fetcher(org.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
    // The fetcher is a fresh closure each render; the org is the real input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = () => {
    setRefreshing(true);
    load();
  };
  return { data, loading, refreshing, error, refresh, reload: load };
}
