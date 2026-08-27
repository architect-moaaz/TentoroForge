import { create } from "zustand";
import { api, ApiError } from "@/lib/api";

interface OrgMembership {
  org_id: string;
  org_name: string;
  org_slug: string;
  role: string;
}

interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
  orgs: OrgMembership[];
}

interface AuthState {
  token: string | null;
  user: User | null;
  isLoading: boolean;
  /** True once hydrate() has run (from localStorage). Guards route protection
   * so AuthGuard doesn't redirect to /login before the persisted token is read
   * — otherwise every full page load / deep link bounces an authed user out. */
  hydrated: boolean;
  error: string | null;

  signup: (email: string, name: string, password: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  fetchUser: () => Promise<void>;
  clearError: () => void;
  hydrate: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  user: null,
  isLoading: false,
  hydrated: false,
  error: null,

  signup: async (email, name, password) => {
    set({ isLoading: true, error: null });
    try {
      const data = await api.post<{
        access_token: string;
        refresh_token: string | null;
      }>("/api/auth/signup", { email, name, password });
      localStorage.setItem("token", data.access_token);
      if (data.refresh_token) {
        localStorage.setItem("refresh_token", data.refresh_token);
      }
      set({ token: data.access_token });
      await get().fetchUser();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Signup failed";
      set({ error: message, isLoading: false });
      throw e;
    }
  },

  login: async (email, password) => {
    set({ isLoading: true, error: null });
    try {
      const data = await api.post<{
        access_token: string;
        refresh_token: string | null;
      }>("/api/auth/login", { email, password });
      localStorage.setItem("token", data.access_token);
      if (data.refresh_token) {
        localStorage.setItem("refresh_token", data.refresh_token);
      }
      set({ token: data.access_token });
      await get().fetchUser();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Login failed";
      set({ error: message, isLoading: false });
      throw e;
    }
  },

  logout: async () => {
    try {
      await api.post("/api/auth/logout");
    } catch {
      // Ignore errors on logout
    }
    localStorage.removeItem("token");
    localStorage.removeItem("refresh_token");
    set({ token: null, user: null, error: null });
  },

  fetchUser: async () => {
    try {
      const user = await api.get<User>("/api/auth/me");
      set({ user, isLoading: false });
    } catch (err) {
      // A9-2: this used to be a bare `catch` that deleted the token on ANY
      // failure. It could not tell "your credentials are invalid" (401/403 —
      // clearing is correct) from "the request did not complete": offline,
      // DNS, timeout, 5xx, or a CORS rejection. All of them destroyed a VALID
      // session with no message, and the recovery — sign in again — is the
      // worst outcome if the user had unsaved work.
      //
      // Only an explicit auth rejection clears the session now. Anything else
      // keeps the token and stops loading, so the app can retry.
      const status = err instanceof ApiError ? err.status : undefined;
      if (status === 401 || status === 403) {
        localStorage.removeItem("token");
        localStorage.removeItem("refresh_token");
        set({ token: null, user: null, isLoading: false });
      } else {
        set({ isLoading: false });
      }
    }
  },

  clearError: () => set({ error: null }),

  hydrate: () => {
    const token = localStorage.getItem("token");
    if (token) {
      set({ token, isLoading: true, hydrated: true });
      get().fetchUser();
    } else {
      set({ hydrated: true });
    }
  },
}));
