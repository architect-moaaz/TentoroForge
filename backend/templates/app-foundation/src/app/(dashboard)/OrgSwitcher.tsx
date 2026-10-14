"use client";
/**
 * The organisation I act in, and the others I may switch to. Rendered in the
 * frame's cluster when the application has several organisations and I
 * belong to more than one (or hold a platform role). Switching updates the
 * session (`update()`), so the role and every scoped list follow.
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { apiPath } from "@/lib/api-path";

export function OrgSwitcher() {
  const router = useRouter();
  const { update } = useSession();
  const [state, setState] = React.useState<{ organisations: Array<{ orgId: string; orgName?: string | null; address?: string }>; activeOrgId: string | null } | null>(null);
  React.useEffect(() => {
    let alive = true;
    fetch(apiPath("/api/org"), { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((b) => { if (alive && b) setState(b); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!state || state.organisations.length < 2) return null;
  return (
    <select aria-label="Organisation" className="rounded border border-border bg-background px-2 py-1 text-sm" value={state.activeOrgId ?? ""}
            onChange={async (e) => {
              const orgId = e.target.value;
              // AN ORGANISATION WITH ITS OWN ADDRESS is switched to by going there.
              const address = state.organisations.find((o) => o.orgId === orgId)?.address;
              if (address) { window.location.href = address; return; }
              const res = await fetch(apiPath("/api/org"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ orgId }) });
              if (res.ok) { setState({ ...state, activeOrgId: orgId }); await update(); router.refresh(); }
            }}>
      {state.organisations.map((o) => <option key={o.orgId} value={o.orgId}>{o.orgName ?? o.orgId.slice(0, 8)}</option>)}
    </select>
  );
}
