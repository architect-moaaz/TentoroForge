"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth";

/**
 * The cockpit opens for the super admin and nobody else. AuthGuard has
 * already sent a signed-out person to /login and waited for the user to
 * load, so by the time this renders there is a user to ask.
 */
export function SuperAdminGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const allowed = !!user && user.platform_role === "super_admin" && !user.impersonated_by;

  useEffect(() => {
    if (user && !allowed) router.replace("/");
  }, [user, allowed, router]);

  if (!allowed) return null;
  return <>{children}</>;
}
