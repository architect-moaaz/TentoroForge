// The app SDK (native) — who is signed in. `SessionProvider` wraps the app (the
// root layout does it); a screen reads `useSession()`.
//
//   const { user, status, signIn, signOut, refresh } = useSession();
//
// `status` is the whole truth about the session, so a screen never guesses:
//   "loading"    the saved session is being checked (the splash is up);
//   "signedIn"   `user` is the person (role, every profile column);
//   "signedOut"  no session — a visitor (public pages), or the login screen;
//   "offline"    the app could not be reached, so we cannot say. The saved
//                session is kept and `refresh()` tries again; the root layout
//                shows a retry rather than sending a signed-in person to /login.
//
// A 401 on any call tells the provider the session is gone (`signed-out`
// event): `status` becomes "signedOut" and the layout returns to /login.
//
// ORGANISATIONS. When the app has several (tenancy on), writes are refused until
// one is active. After a session is read, the provider asks `/api/org`: one
// organisation is chosen for the person; several set `needsOrganisation`, and
// the layout shows the picker (app/organisation.tsx) built on `useOrganisations()`.
//
// Only password sign-in is native. `useSignInMethods()` says what the app
// offers; the login screen explains when password sign-in is not one of them.

import * as React from "react";
import { client, restoreCookies } from "./api";
import { signedOut } from "./events";
import {
  fetchMethods, fetchOrganisations, fetchSession, signInWithPassword, signOutRequest, switchOrganisation as switchRequest,
  type Organisation, type SessionUser, type SignInMethods, type SignInOutcome,
} from "./signin";

export type { SessionUser, SignInMethods, SignInOutcome, Organisation };

export type SessionStatus = "loading" | "signedIn" | "signedOut" | "offline";

interface SessionValue {
  user: SessionUser | null;
  status: SessionStatus;
  signIn: (email: string, password: string) => Promise<SignInOutcome>;
  signOut: () => Promise<void>;
  /** Read the session again (after the server may have changed it). */
  refresh: () => Promise<void>;
  organisations: Organisation[];
  activeOrgId: string | null;
  needsOrganisation: boolean;
  switchOrganisation: (orgId: string) => Promise<{ ok: true } | { ok: false; message: string }>;
}

const SessionContext = React.createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<SessionUser | null>(null);
  const [status, setStatus] = React.useState<SessionStatus>("loading");
  const [organisations, setOrganisations] = React.useState<Organisation[]>([]);
  const [activeOrgId, setActiveOrgId] = React.useState<string | null>(null);

  /** The organisation step after a session is known. */
  const settleOrganisation = React.useCallback(async (who: SessionUser): Promise<SessionUser> => {
    try {
      const list = await fetchOrganisations(client);
      setOrganisations(list.organisations);
      let current = who;
      let active = who.activeOrgId ?? list.activeOrgId;
      // Nothing to choose between: the one organisation is the person's.
      if (!active && list.organisations.length === 1) {
        const out = await switchRequest(client, list.organisations[0].orgId);
        if (out.ok) { active = list.organisations[0].orgId; if (out.user) current = out.user; }
      }
      setActiveOrgId(active ?? null);
      return current;
    } catch {
      return who; // offline for this call: the session stands, the picker waits
    }
  }, []);

  const refresh = React.useCallback(async () => {
    await restoreCookies();
    try {
      const who = await fetchSession(client);
      if (!who) { setUser(null); setOrganisations([]); setActiveOrgId(null); setStatus("signedOut"); return; }
      const settled = await settleOrganisation(who);
      setUser(settled);
      setStatus("signedIn");
    } catch {
      // Could not ask. Keep what we have; a first launch with nothing is "offline".
      setStatus((s) => (s === "signedIn" ? s : "offline"));
    }
  }, [settleOrganisation]);

  React.useEffect(() => { void refresh(); }, [refresh]);

  React.useEffect(() => signedOut.subscribe(() => {
    setUser(null); setOrganisations([]); setActiveOrgId(null); setStatus("signedOut");
  }), []);

  const signIn = React.useCallback(async (email: string, password: string) => {
    const out = await signInWithPassword(client, email.trim(), password);
    if (out.ok) {
      const settled = await settleOrganisation(out.user);
      setUser(settled);
      setStatus("signedIn");
      return { ok: true, user: settled } as SignInOutcome;
    }
    return out;
  }, [settleOrganisation]);

  const signOut = React.useCallback(async () => {
    await signOutRequest(client);
    setUser(null); setOrganisations([]); setActiveOrgId(null); setStatus("signedOut");
  }, []);

  const switchOrganisation = React.useCallback(async (orgId: string) => {
    const out = await switchRequest(client, orgId);
    if (!out.ok) return out;
    if (out.user) setUser(out.user);
    setActiveOrgId(orgId);
    return { ok: true } as const;
  }, []);

  const value = React.useMemo<SessionValue>(() => ({
    user, status, signIn, signOut, refresh, organisations, activeOrgId,
    needsOrganisation: status === "signedIn" && organisations.length > 1 && !activeOrgId,
    switchOrganisation,
  }), [user, status, signIn, signOut, refresh, organisations, activeOrgId, switchOrganisation]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Pick<SessionValue, "user" | "status" | "signIn" | "signOut" | "refresh"> {
  const v = React.useContext(SessionContext);
  if (!v) throw new Error("useSession needs the SessionProvider (app/_layout.tsx wraps the app in it).");
  const { user, status, signIn, signOut, refresh } = v;
  return { user, status, signIn, signOut, refresh };
}

/** The organisations the person may act in and the one they act in.
 *  `switchOrganisation(orgId)` chooses (POST /api/org) and refreshes the
 *  session, so the role and every scoped read follow. Empty `organisations`:
 *  the app has one organisation, and there is nothing to pick. */
export function useOrganisations(): Pick<SessionValue, "organisations" | "activeOrgId" | "needsOrganisation" | "switchOrganisation"> {
  const v = React.useContext(SessionContext);
  if (!v) throw new Error("useOrganisations needs the SessionProvider (app/_layout.tsx wraps the app in it).");
  const { organisations, activeOrgId, needsOrganisation, switchOrganisation } = v;
  return { organisations, activeOrgId, needsOrganisation, switchOrganisation };
}

/** How the app lets people in (GET /api/auth/methods). */
export function useSignInMethods(): { methods: SignInMethods | null; loading: boolean; error: string | null; retry: () => void } {
  const [methods, setMethods] = React.useState<SignInMethods | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setError(null);
    fetchMethods(client).then((m) => { if (live) setMethods(m); })
      .catch((e: unknown) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [attempt]);
  const retry = React.useCallback(() => setAttempt((n) => n + 1), []);
  return { methods, loading: methods === null && error === null, error, retry };
}
