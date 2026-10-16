"use client";

/**
 * Settings › Usage & Cost — the organisation's standing (credit, spend,
 * limits) atop what each app build cost (tokens + dollars, per app /
 * pipeline phase / model / day). The API is admin-gated, so non-admins
 * see a clear "admin role required" message.
 */

import { use } from "react";
import { OrgBalanceCard } from "@/components/usage/OrgBalanceCard";
import { UsageDashboard } from "@/components/usage/UsageDashboard";

export default function SettingsUsagePage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  return (
    <>
      <div className="px-6 pt-6"><OrgBalanceCard orgId={orgId} /></div>
      <UsageDashboard />
    </>
  );
}
