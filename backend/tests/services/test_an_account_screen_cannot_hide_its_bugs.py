"""The phone Account screen that drew nothing and signed nobody out.

Cart Buddy's Account screen read `account` off `useMe() as any` (it is `data.account`, so it was always undefined and the
screen drew only its title) and signed out with the plan's "Sign Out" workflow (a single "end" step: the session stayed, and the
sign-in screen sent the person straight back in). The compiler passed it, because `as any` switched the compiler off for that
line. The writer's guide even said `useMe() // { user, account }`. Now: the guide says what it returns, and both habits are
refused with the way out."""
from __future__ import annotations

from pathlib import Path

from services.blueprint import native_engineer as ne

BROKEN = '''
import { Screen as AppScreen, Text, Button, Stack } from "@/ui";
import { useMe, useWorkflow, workflows, pages, href } from "@/sdk";

export default function Screen() {
  const { account, loading } = useMe() as any;
  const { run, pending } = useWorkflow(workflows.signOut, { redirectTo: href(pages.signIn) });
  return (
    <AppScreen title="Account" loading={loading}>
      {account && (<Stack><Text>{account.email}</Text><Button onPress={() => run({ shopper: account.id })} loading={pending}>Sign out</Button></Stack>)}
    </AppScreen>
  );
}
'''

FIXED = '''
import { useState } from "react";
import { Screen as AppScreen, Text, Button, Stack } from "@/ui";
import { useMe, useSession } from "@/sdk";

export default function Screen() {
  const { data, loading } = useMe();
  const { signOut } = useSession();
  const [pending, setPending] = useState(false);
  const account = data?.account;
  return (
    <AppScreen title="Account" loading={loading}>
      {account && (<Stack><Text>{account.email}</Text><Button onPress={async () => { setPending(true); await signOut(); setPending(false); }} loading={pending}>Sign out</Button></Stack>)}
    </AppScreen>
  );
}
'''


def said(screen: str) -> str:
    return "\n".join(ne._native_findings(screen))


def test_as_any_is_refused_with_the_real_shape():
    text = said(BROKEN)
    assert "`as any`" in text and "data?.account" in text


def test_a_sign_out_workflow_is_refused_with_the_real_sign_out():
    text = said(BROKEN)
    assert "does not sign anyone out" in text and "useSession()" in text and "signOut()" in text


def test_the_fixed_screen_is_not_refused_for_either():
    text = said(FIXED)
    assert "as any" not in text and "sign anyone out" not in text


def test_other_uses_of_a_workflow_are_untouched():
    screen = FIXED + "\nconst x = workflows.addItemToList; const y = workflows.signOutEverywhere;\n"
    assert "sign anyone out" not in said(screen)


def test_the_writers_guide_says_what_use_me_returns():
    guide = ne.sdk_guide()
    assert "data = { user, account }" in guide
    assert "const { account } = useMe()` is always undefined" in guide
    assert "SIGNING OUT IS `useSession().signOut()`" in guide
