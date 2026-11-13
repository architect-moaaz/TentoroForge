"use client";

/**
 * /org/[orgId]/settings/payments — moved. Payment gateways are the Payments
 * group of Settings → Integrations, beside every other service the apps are
 * wired to (`components/payments/GatewaysSection`). This address, linked from
 * older messages, bookmarks and Smith's answers, goes there.
 */

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";
import { paymentsSettingsHref } from "@/lib/payment-gateways";

export default function PaymentsSettingsMoved({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = use(params);
  const router = useRouter();
  useEffect(() => { router.replace(paymentsSettingsHref(orgId)); }, [router, orgId]);
  return <div className="p-8 text-sm text-muted-foreground">Payments are under Integrations now — opening them…</div>;
}
