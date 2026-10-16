// Choose an organisation — fixed, the same in every app. An app with several
// organisations (tenancy on) refuses writes until one is active, so a person who
// belongs to more than one is sent here after signing in (the root layout does
// it). Choosing calls POST /api/org and refreshes the session; the layout then
// moves on. Also reachable later to switch: `nav.push("/organisation")`.

import * as React from "react";
import { Empty, ListItem, ListView, Screen } from "@/ui";
import { toast, useNav, useOrganisations } from "@/sdk";
import { HOME } from "@/config.generated";

export default function ChooseOrganisation() {
  const nav = useNav();
  const { organisations, activeOrgId, switchOrganisation } = useOrganisations();
  const [busy, setBusy] = React.useState<string | null>(null);

  const choose = async (orgId: string) => {
    setBusy(orgId);
    const out = await switchOrganisation(orgId);
    setBusy(null);
    if (!out.ok) { toast.error(out.message); return; }
    nav.replace(HOME);
  };

  return (
    <Screen title="Choose an organisation" scroll={false}>
      <ListView
        list={{ data: organisations, loading: false, refreshing: false, error: null, refetch: async () => undefined }}
        keyExtractor={(o) => o.orgId}
        empty={<Empty title="No organisations" message="You do not belong to any organisation yet. Ask an administrator to add you." />}
        renderItem={(o) => (
          <ListItem
            title={o.orgName ?? `Organisation ${o.orgId.slice(0, 8)}`}
            subtitle={[o.role, o.orgId === activeOrgId ? "Current" : null].filter(Boolean).join(" · ") || undefined}
            onPress={busy ? undefined : () => { void choose(o.orgId); }}
          />
        )}
      />
    </Screen>
  );
}
