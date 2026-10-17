import { hasCockpitReturn, restoreCockpitReturn } from "@/lib/auth-storage";

// `??` not `||` — `""` means "same-origin, let nginx route /api" and
// must NOT trigger the localhost dev fallback. Only undefined does.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

/**
 * `fetch` as the signed-in person. The editor, the IR and design panels and
 * the Smith panel built their own requests without the bearer, and the
 * routes they call answered anyone who knew a project's folder; those routes
 * want a member now, so every request carries the token the person has
 * (a header the caller already set is kept).
 */
export function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const headers = new Headers(init.headers || {});
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    /** The server's `detail` as sent — a structured refusal keeps its parts. */
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  // A FILE IS NOT JSON. Every request was labelled application/json, the
  // uploads too, so a multipart body went out without its boundary and the
  // server could not read the file. The browser labels FormData itself.
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isForm ? {} : { "Content-Type": "application/json" }),
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });

  // Handle 401 — attempt token refresh
  if (res.status === 401 && token) {
    // AN IMPERSONATION THAT RAN OUT IS NOT A SIGN-OUT. The super admin's own
    // tokens were kept for the way back; they come back and the cockpit
    // opens, instead of a refresh that cannot happen and a login page.
    if (typeof window !== "undefined" && hasCockpitReturn()) {
      restoreCockpitReturn();
      window.location.href = "/admin/people?expired=1";
      throw new ApiError(401, "Impersonation ended");
    }
    // A request that was already in flight when someone else refreshed comes
    // back 401 holding a token that is simply out of date. Refreshing again
    // would present the rotated token and fail, logging the user out for a
    // race they already won — so retry with what is current instead.
    const current =
      typeof window !== "undefined" ? localStorage.getItem("token") : null;
    const refreshed =
      current && current !== token ? true : await attemptTokenRefresh();
    if (refreshed) {
      // Retry with new token
      headers["Authorization"] = `Bearer ${localStorage.getItem("token")}`;
      const retryRes = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers,
        credentials: "include",
      });
      if (retryRes.ok) {
        if (retryRes.status === 204) return undefined as T;
        return retryRes.json();
      }
    }
    // Refresh failed — clear auth state
    localStorage.removeItem("token");
    localStorage.removeItem("refresh_token");
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const message =
      body.error?.message || describeDetail(body.detail) || body.message || res.statusText;
    const code = body.error?.code;
    throw new ApiError(res.status, message, code, body.detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

/**
 * Turn a FastAPI `detail` into something a human can read.
 *
 * A9-1: `detail` was assigned straight to a string `message`. On a 422 FastAPI
 * returns it as an ARRAY OF OBJECTS:
 *
 *   {"detail":[{"type":"value_error","loc":["body","email"],
 *               "msg":"value is not a valid email address: ...", ...}]}
 *
 * so the user saw literally "[object Object]" while the genuinely useful text
 * sat one field down. This affected EVERY 422 in the product, not just auth.
 *
 * Returns "" when there is nothing usable, so the caller's `||` chain moves on
 * to the next candidate rather than showing an empty toast.
 */
export function describeDetail(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === "string") return d;
        if (d && typeof d === "object") {
          const { msg, loc } = d as { msg?: string; loc?: unknown[] };
          // `loc` names the offending field — worth keeping, it is usually the
          // difference between "invalid" and "which one?".
          const where = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
          if (msg) return where ? `${where}: ${msg}` : msg;
        }
        return "";
      })
      .filter(Boolean)
      .join("; ");
  }
  if (typeof detail === "object") {
    const { msg, message } = detail as { msg?: string; message?: string };
    return msg ?? message ?? "";
  }
  return String(detail);
}

// The single refresh in flight, shared by every caller.
//
// Refresh tokens are single-use: /api/auth/refresh rotates the token and
// invalidates the one presented. This function was called per-request, so two
// requests 401ing together fired two refreshes — the first rotated the token
// and returned 200, the second presented the consumed one and got 401, and a
// failed refresh clears localStorage and redirects to /login.
//
// That is not a rare interleaving. The project page loads the project and its
// latest deployment side by side, so an expired access token produces exactly
// two simultaneous 401s and the user is signed out mid-build. Observed at
// 22:54: `POST /api/auth/refresh 200` and `POST /api/auth/refresh 401` in the
// same millisecond.
//
// So the first caller performs the refresh and everyone else awaits the same
// promise. Cleared in `finally` so the next expiry refreshes again.
let refreshInFlight: Promise<boolean> | null = null;

function attemptTokenRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = performTokenRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function performTokenRefresh(): Promise<boolean> {
  const refreshToken = localStorage.getItem("refresh_token");
  if (!refreshToken) return false;

  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!res.ok) return false;

    const data = await res.json();
    localStorage.setItem("token", data.access_token);
    if (data.refresh_token) {
      localStorage.setItem("refresh_token", data.refresh_token);
    }
    return true;
  } catch {
    return false;
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, formData: FormData) =>
    request<T>(path, {
      method: "POST",
      body: formData,
      headers: {}, // Let browser set Content-Type with boundary
    }),
};

export { ApiError };
