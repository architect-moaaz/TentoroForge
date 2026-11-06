"use client";
// The way to a plan, in sight.
//
// An app that stays open while it sells plans showed them only inside the
// account menu: a member signed up, used the app, and never learned a plan
// existed (Task Board, 2026-11-06). Shown once the app says this person holds
// no plan: asked, not taken from the session, which an older app's sign-in
// never fills and which catches up only within the minute after a payment.
// Never on the plan page or a payment page.

import * as React from "react";
import { usePathname } from "next/navigation";
import { Sparkles } from "lucide-react";

export function PlanPrompt() {
  const pathname = usePathname() || "/";
  const [none, setNone] = React.useState(false);
  const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");
  React.useEffect(() => {
    fetch(`${base}/api/billing/status`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => setNone(Boolean(j && !j.access && j.plans?.length)))
      .catch(() => setNone(false));
  }, [base]);
  if (!none || /^\/(billing|pay)(\/|$)/.test(pathname)) return null;
  return (
    <a href={`${base}/billing`} data-plan-prompt=""
      className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-primary px-3.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90">
      <Sparkles size={14} aria-hidden /> Choose a plan
    </a>
  );
}
