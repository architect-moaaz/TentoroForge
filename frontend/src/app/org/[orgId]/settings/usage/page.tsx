"use client";

/**
 * Settings › Usage & Cost — org-admin view of what each app build cost
 * (tokens + dollars, per app / pipeline phase / model / day). Renders
 * the same dashboard as /admin/usage; the API is admin-gated so
 * non-admins see a clear "admin role required" message.
 */

import { UsageDashboard } from "@/components/usage/UsageDashboard";

export default function SettingsUsagePage() {
  return <UsageDashboard />;
}
