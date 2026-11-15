import * as SecureStore from 'expo-secure-store';

import { API_BASE } from './config';

const ACCESS_KEY = 'access_token';
const REFRESH_KEY = 'refresh_token';

let accessToken: string | null = null;
let onSignedOut: (() => void) | null = null;

export function setSignedOutHandler(fn: () => void) {
  onSignedOut = fn;
}

export function getAccessToken() {
  return accessToken;
}

export async function loadTokens() {
  accessToken = await SecureStore.getItemAsync(ACCESS_KEY);
  return accessToken;
}

export async function saveTokens(access: string, refresh?: string | null) {
  accessToken = access;
  await SecureStore.setItemAsync(ACCESS_KEY, access);
  if (refresh) await SecureStore.setItemAsync(REFRESH_KEY, refresh);
}

export async function clearTokens() {
  accessToken = null;
  await SecureStore.deleteItemAsync(ACCESS_KEY);
  await SecureStore.deleteItemAsync(REFRESH_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** 'ok' = new tokens saved; 'invalid' = the server refused the refresh token (sign out);
 *  'offline' = we could not tell (no signal, server error): keep the tokens. */
type RefreshResult = 'ok' | 'invalid' | 'offline';

async function refreshOnce(): Promise<RefreshResult> {
  const refreshToken = await SecureStore.getItemAsync(REFRESH_KEY);
  if (!refreshToken) return 'invalid';
  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (res.status === 401 || res.status === 403) return 'invalid';
    if (!res.ok) return 'offline';
    const body = await res.json();
    await saveTokens(body.access_token, body.refresh_token);
    return 'ok';
  } catch {
    return 'offline';
  }
}

// The server uses each refresh token once. Several requests that fail together
// must share one refresh, or the later ones would be refused and sign the person out.
let refreshing: Promise<RefreshResult> | null = null;
function refreshTokens(): Promise<RefreshResult> {
  refreshing ??= refreshOnce().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

/** fetch against the Forge backend. Adds the login token; on a 401 it tries one
 *  refresh, and signs the person out only if the server says the login is no longer valid. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const send = () =>
    fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init.headers as Record<string, string> | undefined),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
    });

  const used = accessToken;
  let res = await send();
  if (res.status === 401 && path !== '/api/auth/login') {
    // Another request may already have refreshed while ours was in flight.
    const result = accessToken !== used && accessToken ? 'ok' : await refreshTokens();
    if (result === 'ok') {
      res = await send();
    } else if (result === 'invalid') {
      await clearTokens();
      onSignedOut?.();
    } else {
      throw new Error('Network request failed: could not renew your login. Check your connection.');
    }
  }
  return res;
}

export function errorText(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, errorText(body, `Request failed (${res.status})`));
  }
  return (await res.json()) as T;
}

export function postJson<T>(path: string, body?: unknown): Promise<T> {
  return apiJson<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
