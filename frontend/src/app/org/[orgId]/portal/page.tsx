"use client";

import { use } from "react";
import { PortalDashboard } from "@/components/portal/PortalDashboard";

export default function PortalPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  return <PortalDashboard orgId={orgId} />;
}
