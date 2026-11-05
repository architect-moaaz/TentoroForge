import { Stack, useLocalSearchParams } from 'expo-router';
import { useMemo, type ComponentType } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { EmptyState } from '@/components/kit';
import { NAV_ITEMS } from '@/lib/nav';
import { useOrg } from '@/lib/org';
import { PortalScreen } from '@/screens/overview';
import {
  DepartmentsScreen,
  DiscoverScreen,
  DraftsRoomScreen,
  GroupsScreen,
  PeopleScreen,
  RolesScreen,
  TeamsScreen,
  TemplatesScreen,
} from '@/screens/lists';
import { ImportScreen, OrgChartScreen, SettingsScreen } from '@/screens/org';
import { ProjectsScreen } from '@/screens/projects';
import { useColors, type Palette } from '@/theme';

const SCREENS: Record<string, ComponentType> = {
  portal: PortalScreen,
  projects: ProjectsScreen,
  'drafts-room': DraftsRoomScreen,
  discover: DiscoverScreen,
  templates: TemplatesScreen,
  people: PeopleScreen,
  departments: DepartmentsScreen,
  teams: TeamsScreen,
  'org-chart': OrgChartScreen,
  roles: RolesScreen,
  groups: GroupsScreen,
  import: ImportScreen,
  settings: SettingsScreen,
};

/** One screen per sidebar item, picked by the key in the address. */
export default function Section() {
  const { key } = useLocalSearchParams<{ key: string }>();
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const { org, isLocked, featureName } = useOrg();

  const item = NAV_ITEMS.find((i) => i.key === key);
  const Screen = key ? SCREENS[key] : undefined;

  if (!item || !Screen) {
    return (
      <View style={styles.flex}>
        <EmptyState icon="compass" title="Page not found" />
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      <Stack.Screen options={{ title: item.label }} />
      {!org ? (
        <ActivityIndicator style={{ marginTop: 48 }} color={colors.primary} />
      ) : isLocked(item.feature) ? (
        <EmptyState
          icon="lock"
          title={`${item.label} is not enabled`}
          text={`${featureName(item.feature ?? item.label)} is not turned on for your organisation. Ask a platform admin to enable it.`}
        />
      ) : (
        <Screen />
      )}
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    flex: { flex: 1, backgroundColor: colors.surfaceSecondary },
  });
