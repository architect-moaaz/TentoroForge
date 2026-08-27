"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { token, user, hydrated } = useAuthStore();

  useEffect(() => {
    // Only redirect once hydration has actually run. Before that the store's
    // token is null purely because localStorage hasn't been read yet — bouncing
    // here is the auth-hydration race that logged authed users out on reload.
    if (hydrated && !token) {
      router.replace("/login");
    }
  }, [hydrated, token, router]);

  // Show the spinner until we've hydrated AND (when authed) fetched the user.
  if (!hydrated || (token && !user)) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (!token || !user) return null;

  return <>{children}</>;
}
