/**
 * Where the session lives in the browser, and the cockpit's way back.
 *
 * A super admin acting as a person swaps their own tokens for a 30-minute
 * impersonation token. Their own pair is kept in sessionStorage under
 * COCKPIT_RETURN_KEY for the way back — pressed, or forced when the
 * impersonation token expires — and never travels anywhere.
 */
export const TOKEN_KEY = "token";
export const REFRESH_KEY = "refresh_token";
export const COCKPIT_RETURN_KEY = "cockpit_return";

interface CockpitReturn {
  token: string;
  refresh_token: string | null;
  saved_at: number;
}

function storage(kind: "local" | "session"): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function saveCockpitReturn(): boolean {
  const local = storage("local");
  const session = storage("session");
  if (!local || !session) return false;
  const token = local.getItem(TOKEN_KEY);
  if (!token) return false;
  session.setItem(COCKPIT_RETURN_KEY, JSON.stringify({
    token, refresh_token: local.getItem(REFRESH_KEY), saved_at: Date.now(),
  } satisfies CockpitReturn));
  return true;
}

export function readCockpitReturn(): CockpitReturn | null {
  const session = storage("session");
  if (!session) return null;
  try {
    const raw = session.getItem(COCKPIT_RETURN_KEY);
    return raw ? (JSON.parse(raw) as CockpitReturn) : null;
  } catch {
    return null;
  }
}

/** Put the admin's own tokens back; true when there were any. */
export function restoreCockpitReturn(): boolean {
  const saved = readCockpitReturn();
  const local = storage("local");
  const session = storage("session");
  if (!saved || !local) return false;
  local.setItem(TOKEN_KEY, saved.token);
  if (saved.refresh_token) local.setItem(REFRESH_KEY, saved.refresh_token);
  else local.removeItem(REFRESH_KEY);
  session?.removeItem(COCKPIT_RETURN_KEY);
  return true;
}

export function hasCockpitReturn(): boolean {
  return readCockpitReturn() !== null;
}
