// The More tab - fixed, the same in every app whose main pages do not all fit the tab bar. A bar holds four or
// five tabs; the pages after them are listed here, one row each, and open on top of the bar with a back button.
//
// Written into an app only when it has such pages (`native_projection.more_pages`): the list is `MORE` in
// `src/navigation.generated.ts`.

import { Card, Icon, Row, Screen, Stack, Text } from "@/ui";
import { useNav } from "@/sdk";
import { MORE } from "@/navigation.generated";
import type { IconName } from "@/ui";

export default function MoreScreen() {
  const nav = useNav();
  return (
    <Screen title="More" subtitle="Everything else in the app">
      <Stack gap="sm">
        {MORE.map((item) => (
          <Card key={item.route} onPress={() => nav.push(item.route)} accessibilityLabel={item.title}>
            <Row gap="md" align="center">
              <Icon name={item.icon as IconName} size={22} />
              <Text weight="semibold" style={{ flex: 1 }} numberOfLines={1}>{item.title}</Text>
              <Icon name="chevron-forward" size={18} tone="muted" />
            </Row>
          </Card>
        ))}
      </Stack>
    </Screen>
  );
}
