// next-auth/react for the editor's JIT preview. The real module reads Node's
// `process` at load and talks to /api/auth — neither exists in a canvas —
// and the SDK's sign-in forms import it, so every page's preview (they all
// import @/sdk/client) failed with "process is not defined". Here a sign-in
// is only drawn: it reports success and stays where it is.
import * as React from "react";

const SESSION = { user: { id: "sample-user", name: "Sample Admin", email: "admin@example.com" }, expires: "2099-01-01T00:00:00.000Z" };

export async function signIn(_provider?: string, _opts?: Record<string, unknown>) {
  return { ok: true, error: null, status: 200, url: null };
}
export async function signOut(_opts?: Record<string, unknown>) { return { url: "/" }; }
export async function getSession() { return SESSION; }
export async function getCsrfToken() { return "sample-csrf"; }
export function useSession() { return { data: SESSION, status: "authenticated" as const, update: async () => SESSION }; }
export function SessionProvider({ children }: { children?: React.ReactNode }) { return <>{children}</>; }
