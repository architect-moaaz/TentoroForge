"use client";

import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { useAuthStore } from "@/stores/auth";

/**
 * Shown on every page while a super admin is acting as a person — the
 * person's own organisation pages are where it matters, so it lives in
 * the providers, not in the cockpit's layout.
 */
export function ImpersonationBanner() {
  const user = useAuthStore((s) => s.user);
  const endImpersonation = useAuthStore((s) => s.endImpersonation);
  const router = useRouter();
  const queryClient = useQueryClient();
  if (!user?.impersonated_by) return null;

  async function back() {
    await endImpersonation();
    queryClient.clear();
    router.push("/admin/people");
  }

  return (
    <div className="sticky top-0 z-[60] flex items-center justify-between gap-3 bg-amber-500 px-4 py-2 text-sm text-amber-950">
      <span className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4" />
        Viewing as <strong>{user.email}</strong> — every change is recorded under {user.impersonated_by.email}.
      </span>
      <button onClick={back} className="rounded-md bg-amber-950 px-3 py-1 text-xs font-medium text-amber-50 hover:bg-amber-900">
        Return to cockpit
      </button>
    </div>
  );
}
