import { Feather } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { Stack, useRouter, type Href } from 'expo-router';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { EmptyState, IconButton, IconTile, ListRow, RowGroup, SectionLabel } from '@/components/kit';
import { SettingsSheet } from '@/components/settings-sheet';
import { NAV_GROUPS, type NavItem } from '@/lib/nav';
import { useOrg } from '@/lib/org';
import { useSession } from '@/lib/session';
import { radius, shadow, space, type, useColors, type Palette } from '@/theme';

// One quiet tint per menu group, so groups are easy to tell apart at a glance.
const GROUP_TINTS = ['#6172f3', '#8b5cf6', '#0ea5e9', '#64748b'];

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

/** Home: a hero card into Projects, then the web sidebar as grouped menu rows. */
export default function Home() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { signOut } = useSession();
  const { org, orgs, loading, error, reload, isLocked, featureName } = useOrg();
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const open = (item: NavItem) => {
    if (isLocked(item.feature)) {
      Alert.alert(
        `${item.label} is locked`,
        `${featureName(item.feature ?? item.label)} is not turned on for your organisation. Ask a platform admin to enable it.`,
      );
      return;
    }
    // The typed-route list is rebuilt when Expo starts, so a route added in
    // this session is not in it yet; hence the cast.
    router.push(`/s/${item.key}` as Href);
  };

  // Projects gets the hero card, so it is left out of the rows below.
  const groups = NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter((i) => i.key !== 'projects') })).filter(
    (g) => g.items.length > 0,
  );

  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <Stack.Screen options={{ headerShown: false }} />
      <SettingsSheet visible={settingsOpen} onClose={() => setSettingsOpen(false)} onSignOut={signOut} />

      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.greeting}>{greeting()}</Text>
          <Text style={styles.title} numberOfLines={1}>
            {org?.name ?? 'Tentoro Forge'}
          </Text>
        </View>
        <IconButton name="settings" label="Settings" onPress={() => setSettingsOpen(true)} />
      </View>

      {loading && !org ? (
        <ActivityIndicator style={{ marginTop: 48 }} color={colors.primary} />
      ) : !org ? (
        <EmptyState
          icon={error ? 'alert-circle' : 'briefcase'}
          tone={error ? 'error' : 'neutral'}
          title={error ? 'Could not load' : 'No organisation yet'}
          text={error ?? (orgs.length === 0 ? 'Create or join an organisation on the web app.' : null)}
          action={{ label: 'Try again', onPress: reload }}
        />
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingHorizontal: space.lg, paddingBottom: space.xxxl + insets.bottom, gap: space.xxl }}
          showsVerticalScrollIndicator={false}>
          <Pressable onPress={() => router.push('/s/projects' as Href)} style={({ pressed }) => [pressed && { opacity: 0.92 }]}>
            <LinearGradient colors={['#2b0d55', '#1b0838']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.hero}>
              <View style={[styles.ring, { width: 200, height: 200, top: -60, right: -60 }]} />
              <View style={[styles.ring, { width: 120, height: 120, top: -20, right: -20 }]} />
              <View style={styles.heroIcon}>
                <Feather name="folder" size={20} color="#fff" />
              </View>
              <Text style={styles.heroTitle}>Your projects</Text>
              <Text style={styles.heroText}>Chat with Smith, see live previews and change your apps from here.</Text>
              <View style={styles.heroCta}>
                <Text style={styles.heroCtaText}>Open projects</Text>
                <Feather name="arrow-right" size={16} color="#1b0838" />
              </View>
            </LinearGradient>
          </Pressable>

          {groups.map((group, gi) => {
            const tint = GROUP_TINTS[gi % GROUP_TINTS.length];
            return (
              <View key={gi}>
                {group.label ? <SectionLabel>{group.label}</SectionLabel> : null}
                <RowGroup>
                  {group.items.map((item, i) => {
                    const locked = isLocked(item.feature);
                    return (
                      <ListRow
                        key={item.key}
                        first={i === 0}
                        title={item.label}
                        dimmed={locked}
                        onPress={() => open(item)}
                        chevron={!locked}
                        leading={<IconTile name={item.icon} tint={locked ? undefined : tint} />}
                        trailing={locked ? <Feather name="lock" size={15} color="#f59e0b" /> : null}
                      />
                    );
                  })}
                </RowGroup>
              </View>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.surfaceSecondary },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.md,
      paddingHorizontal: space.xl,
      paddingTop: space.md,
      paddingBottom: space.xl,
    },
    greeting: { ...type.callout, color: colors.textSecondary },
    title: { ...type.display, color: colors.text, marginTop: 2 },
    hero: { borderRadius: radius.xxl + 4, padding: space.xl, overflow: 'hidden', ...shadow.float },
    ring: { position: 'absolute', borderRadius: 44, borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.08)' },
    heroIcon: {
      width: 40,
      height: 40,
      borderRadius: radius.lg + 2,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'rgba(255,255,255,0.12)',
      marginBottom: space.lg,
    },
    heroTitle: { ...type.title, fontSize: 22, color: '#fff' },
    heroText: { ...type.callout, color: 'rgba(255,255,255,0.72)', marginTop: space.xs + 2, maxWidth: 280 },
    heroCta: {
      alignSelf: 'flex-start',
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm,
      marginTop: space.xl,
      paddingHorizontal: space.lg,
      height: 40,
      borderRadius: radius.pill,
      backgroundColor: '#fff',
    },
    heroCtaText: { ...type.callout, fontFamily: 'Inter_600SemiBold', color: '#1b0838' },
  });
