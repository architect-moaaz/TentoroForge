// The component kit - a page that has no phone screen (yet). Written into an app as the route of any page the native writer
// could not produce a screen for, so a tab, a menu entry or a link never leads to "This screen does not exist": it says
// what happened and opens the page's web version. When the screen is written later, its route file is replaced by it.

import { Linking } from "react-native";
import { appUrl } from "../sdk";
import { Button } from "./Button";
import { Screen } from "./Screen";
import { Empty } from "./States";

export function MissingScreen({ title, route }: { title: string; route: string }) {
  return (
    <Screen title={title}>
      <Empty
        icon="phone-portrait-outline"
        title="Not on the phone yet"
        message={`${title} has not been written for the phone yet. It works on the web.`}
        action={<Button variant="outline" icon="open-outline" onPress={() => { void Linking.openURL(appUrl(route)); }}>Open on the web</Button>}
      />
    </Screen>
  );
}
