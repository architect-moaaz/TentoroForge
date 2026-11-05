import * as SecureStore from 'expo-secure-store';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemePref = 'system' | 'light' | 'dark';

const KEY = 'theme_pref';

interface PrefContext {
  pref: ThemePref;
  setPref: (pref: ThemePref) => void;
  /** False until the saved choice has been read, so the first paint is not the wrong theme. */
  ready: boolean;
}

const Ctx = createContext<PrefContext>({ pref: 'system', setPref: () => {}, ready: true });

/** Remembers the person's light, dark or system choice on this device. */
export function ThemePrefProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>('system');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    SecureStore.getItemAsync(KEY)
      .then((value) => {
        if (value === 'light' || value === 'dark' || value === 'system') setPrefState(value);
      })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const setPref = useCallback((next: ThemePref) => {
    setPrefState(next);
    SecureStore.setItemAsync(KEY, next).catch(() => {});
  }, []);

  const value = useMemo(() => ({ pref, setPref, ready }), [pref, setPref, ready]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useThemePref = () => useContext(Ctx);
