// A route that is not a screen — fixed, the same in every app. A link, a push
// notification or a typed address can name a route the app does not have
// (a page removed in a later version); this says so and leads home instead of
// leaving a blank screen.

import * as React from "react";
import { Button, Empty, Screen } from "@/ui";
import { useNav } from "@/sdk";
import { HOME } from "@/config.generated";

export default function NotFound() {
  const nav = useNav();
  return (
    <Screen title="Not found" back={false}>
      <Empty
        title="This screen does not exist"
        message="The link may be out of date."
        action={<Button onPress={() => nav.replace(HOME)}>Go to the start</Button>}
      />
    </Screen>
  );
}
