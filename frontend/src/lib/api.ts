// `??` not `||` — `""` means "same-origin, let nginx route /api" and
// must NOT trigger the localhost dev fallback. Only undefined does.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
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

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
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
    const refreshed = await attemptTokenRefresh();
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
    throw new ApiError(res.status, message, code);
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
    const { msg } = detail as { msg?: string };
    return msg ?? "";
  }
  return String(detail);
}

async function attemptTokenRefresh(): Promise<boolean> {
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
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, formData: FormData) =>
    request<T>(path, {
      method: "POST",
      body: formData,
      headers: {}, // Let browser set Content-Type with boundary
    }),
};

export { ApiError };
