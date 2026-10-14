// The account tab - fixed, the same in every app that has a sign-in: who is signed in, the organisation they
// act in (when the app has several), the language, and SIGN OUT. A tab bar is where a phone's person looks for
// "me"; without this there would be no way out of an app but clearing its data.
//
// Written into an app only when it has a sign-in (`native_projection.account_tab`), as the last tab.

import * as React from "react";
import Constants from "expo-constants";
import { Avatar, Badge, Button, Card, Chips, Dialog, LanguageSwitch, Row, Screen, Stack, Text } from "@/ui";
import { useOrganisations, useSession } from "@/sdk";
import { APP_NAME } from "@/config.generated";

export default function AccountScreen() {
  const { user, signOut } = useSession();
  const { organisations, activeOrgId, switchOrganisation } = useOrganisations();
  const [asking, setAsking] = React.useState(false);
  const [leaving, setLeaving] = React.useState(false);
  const name = user?.name || user?.email || "You";

  const leave = async () => {
    setAsking(false);
    setLeaving(true);
    await signOut();                       // the sign-in gate takes it from here: signed out goes to /login
    setLeaving(false);
  };

  return (
    <Screen title="Account">
      <Card>
        <Row gap="md" align="center">
          <Avatar name={name} size={52} />
          <Stack gap="xs" align="start">
            <Text variant="heading" numberOfLines={1}>{name}</Text>
            {user?.email && user.email !== name ? <Text variant="caption" tone="muted" numberOfLines={1}>{user.email}</Text> : null}
            {user?.role ? <Badge tone="accent">{user.role}</Badge> : null}
          </Stack>
        </Row>
      </Card>

      {organisations.length > 1 ? (
        <Stack gap="sm">
          <Text variant="label" tone="muted">ORGANISATION</Text>
          <Chips
            value={activeOrgId ?? organisations[0].orgId}
            onChange={(id) => { void switchOrganisation(id); }}
            items={organisations.map((o) => ({ key: o.orgId, label: o.orgName ?? o.orgId }))}
          />
        </Stack>
      ) : null}

      <LanguageSwitch />

      <Button variant="outline" icon="log-out-outline" fullWidth loading={leaving} onPress={() => setAsking(true)}>Sign out</Button>
      <Text variant="caption" tone="muted" align="center">{APP_NAME} · version {Constants.expoConfig?.version ?? "1.0.0"}</Text>

      <Dialog visible={asking} message="Sign out of this app on this phone?" confirmLabel="Sign out" variant="danger"
        onCancel={() => setAsking(false)} onConfirm={() => { void leave(); }} />
    </Screen>
  );
}
