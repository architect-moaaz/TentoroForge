import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { apiFetch, clearTokens, errorText, loadTokens, saveTokens, setSignedOutHandler } from './api';
import { API_BASE } from './config';

type Status = 'loading' | 'in' | 'out';

interface Session {
  status: Status;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');

  useEffect(() => {
    setSignedOutHandler(() => setStatus('out'));
    loadTokens().then((token) => setStatus(token ? 'in' : 'out'));
  }, []);

  // Login and sign-up both answer with a token pair; this posts and keeps it.
  const authPost = useCallback(async (path: string, payload: object, failed: string) => {
    let res: Response;
    try {
      res = await apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new Error(`Cannot reach the server at ${API_BASE}`);
    }
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(errorText(body, `${failed} (${res.status})`));
    await saveTokens(body.access_token, body.refresh_token);
    setStatus('in');
  }, []);

  const signIn = useCallback(
    (email: string, password: string) => authPost('/api/auth/login', { email, password }, 'Login failed'),
    [authPost],
  );

  const signUp = useCallback(
    (name: string, email: string, password: string) =>
      authPost('/api/auth/signup', { name, email, password }, 'Sign up failed'),
    [authPost],
  );

  const signOut = useCallback(async () => {
    await clearTokens();
    setStatus('out');
  }, []);

  const value = useMemo(() => ({ status, signIn, signUp, signOut }), [status, signIn, signUp, signOut]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}
