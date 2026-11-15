import { Feather } from '@expo/vector-icons';
import { useRouter, type Href } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Card, EmptyState, LetterTile, SectionLabel, Segmented, SkeletonList, timeAgo } from '@/components/kit';
import { StatusBadge } from '@/components/ui';
import { apiJson } from '@/lib/api';
import type { IconName } from '@/lib/nav';
import { useOrgData } from '@/lib/use-org-data';
import { icon, radius, shadow, space, type, useColors, type Palette } from '@/theme';

/** A number tile. Tappable when it leads somewhere. */
function Stat({
  label,
  value,
  icon: name,
  tint,
  onPress,
}: {
  label: string;
  value: number | string;
  icon: IconName;
  tint: string;
  onPress?: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <Pressable
      style={({ pressed }) => [styles.stat, pressed && onPress && { backgroundColor: colors.muted }]}
      onPress={onPress}
      disabled={!onPress}>
      <View style={styles.statTop}>
        <View style={[styles.statIcon, { backgroundColor: `${tint}1f` }]}>
          <Feather name={name} size={icon.sm + 2} color={tint} />
        </View>
        {onPress ? <Feather name="arrow-up-right" size={icon.sm + 2} color={colors.textTertiary} /> : null}
      </View>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </Pressable>
  );
}

function useScreenStyles() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return { colors, styles, bottom: insets.bottom };
}

interface Suggestion {
  template: { slug: string; name: string; description: string };
  reason?: string;
}

export function DashboardScreen() {
  const { styles, bottom } = useScreenStyles();
  const router = useRouter();
  const go = (key: string) => router.push(`/s/${key}` as Href);

  const { data, loading, refreshing, error, refresh, reload } = useOrgData(async (orgId) => {
    const base = `/api/orgs/${orgId}`;
    const [projects, people, departments, teams, suggested] = await Promise.all([
      apiJson<unknown[]>(`${base}/projects`),
      apiJson<unknown[]>(`${base}/people?limit=200`),
      apiJson<unknown[]>(`${base}/departments`),
      apiJson<unknown[]>(`${base}/teams`),
      apiJson<{ suggestions?: Suggestion[] }>(`${base}/suggested-apps`).catch(() => ({ suggestions: [] })),
    ]);
    return {
      projects: projects.length,
      people: people.length,
      departments: departments.length,
      teams: teams.length,
      suggestions: suggested.suggestions ?? [],
    };
  });

  if (loading) return <SkeletonList />;
  if (error || !data)
    return (
      <EmptyState
        icon="alert-circle"
        tone="error"
        title="Could not load the dashboard"
        text={error}
        action={{ label: 'Try again', onPress: reload }}
      />
    );

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.content, { paddingBottom: space.xxxl + bottom }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}>
      <View style={styles.grid}>
        <Stat label="Projects" value={data.projects} icon="folder" tint="#6172f3" onPress={() => go('projects')} />
        <Stat label="People" value={data.people} icon="users" tint="#0ea5e9" onPress={() => go('people')} />
        <Stat label="Departments" value={data.departments} icon="briefcase" tint="#8b5cf6" onPress={() => go('departments')} />
        <Stat label="Teams" value={data.teams} icon="user-check" tint="#10b981" onPress={() => go('teams')} />
      </View>

      {data.suggestions.length > 0 ? (
        <View>
          <SectionLabel>Suggested apps</SectionLabel>
          <View style={{ gap: space.sm + 2 }}>
            {data.suggestions.map((s) => (
              <Card key={s.template.slug} style={styles.rowCard} padded={false}>
                <LetterTile name={s.template.name} size={40} />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={styles.cardTitle}>{s.template.name}</Text>
                  <Text style={styles.cardText} numberOfLines={3}>
                    {s.reason ?? s.template.description}
                  </Text>
                </View>
              </Card>
            ))}
          </View>
        </View>
      ) : null}
    </ScrollView>
  );
}

interface PortalApp {
  id: string;
  name: string;
  description: string | null;
  status: string;
  badges?: { pending_tasks?: number };
}
interface PortalTask {
  id: string;
  app_name: string;
  title: string;
  status: string;
  due_at: string | null;
}
interface PortalActivity {
  id: string;
  app_name: string;
  title: string;
  description: string | null;
  created_at: string;
}
interface PortalStats {
  total_apps: number;
  active_apps: number;
  pending_tasks: number;
  recent_activity_count: number;
}

type PortalTab = 'apps' | 'tasks' | 'activity';

export function PortalScreen() {
  const { styles, bottom } = useScreenStyles();
  const [tab, setTab] = useState<PortalTab>('apps');

  const { data, loading, refreshing, error, refresh, reload } = useOrgData(async (orgId) => {
    const base = `/api/orgs/${orgId}/portal`;
    const [dash, stats] = await Promise.all([
      apiJson<{ apps?: PortalApp[]; tasks?: PortalTask[]; activity?: PortalActivity[] }>(`${base}/dashboard`),
      apiJson<{ stats?: PortalStats }>(`${base}/stats`).catch(() => ({ stats: undefined })),
    ]);
    return { apps: dash.apps ?? [], tasks: dash.tasks ?? [], activity: dash.activity ?? [], stats: stats.stats };
  });

  if (loading) return <SkeletonList />;
  if (error || !data)
    return (
      <EmptyState icon="alert-circle" tone="error" title="Could not load the portal" text={error} action={{ label: 'Try again', onPress: reload }} />
    );

  const tabs: { id: PortalTab; label: string; count: number }[] = [
    { id: 'apps', label: 'Apps', count: data.apps.length },
    { id: 'tasks', label: 'Tasks', count: data.tasks.length },
    { id: 'activity', label: 'Activity', count: data.activity.length },
  ];
  const empty = tabs.find((t) => t.id === tab)?.count === 0;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.content, { paddingBottom: space.xxxl + bottom }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}>
      {data.stats ? (
        <View style={styles.grid}>
          <Stat label="Apps" value={data.stats.total_apps} icon="grid" tint="#6172f3" />
          <Stat label="Active" value={data.stats.active_apps} icon="activity" tint="#10b981" />
          <Stat label="Pending tasks" value={data.stats.pending_tasks} icon="check-square" tint="#f59e0b" />
          <Stat label="Recent activity" value={data.stats.recent_activity_count} icon="clock" tint="#8b5cf6" />
        </View>
      ) : null}

      <Segmented options={tabs.map((t) => ({ id: t.id, label: `${t.label} · ${t.count}` }))} value={tab} onChange={setTab} />

      <View style={{ gap: space.sm + 2 }}>
        {tab === 'apps' &&
          data.apps.map((a) => (
            <Card key={a.id} style={styles.rowCard} padded={false}>
              <LetterTile name={a.name} size={40} />
              <View style={{ flex: 1, gap: 2 }}>
                <View style={styles.titleRow}>
                  <Text style={styles.cardTitle} numberOfLines={1}>
                    {a.name}
                  </Text>
                  <StatusBadge status={a.status} />
                </View>
                {a.description ? (
                  <Text style={styles.cardText} numberOfLines={2}>
                    {a.description}
                  </Text>
                ) : null}
                {a.badges?.pending_tasks ? <Text style={styles.meta}>{a.badges.pending_tasks} pending tasks</Text> : null}
              </View>
            </Card>
          ))}
        {tab === 'tasks' &&
          data.tasks.map((t) => (
            <Card key={t.id}>
              <View style={styles.titleRow}>
                <Text style={styles.cardTitle}>{t.title}</Text>
                <StatusBadge status={t.status} />
              </View>
              <Text style={styles.meta}>
                {t.app_name}
                {t.due_at ? ` · due ${new Date(t.due_at).toLocaleDateString()}` : ''}
              </Text>
            </Card>
          ))}
        {tab === 'activity' &&
          data.activity.map((a, i) => (
            <View key={a.id} style={styles.timeline}>
              <View style={styles.rail}>
                <View style={styles.dot} />
                {i < data.activity.length - 1 ? <View style={styles.railLine} /> : null}
              </View>
              <View style={{ flex: 1, paddingBottom: space.lg, gap: 2 }}>
                <Text style={styles.cardTitle}>{a.title}</Text>
                {a.description ? <Text style={styles.cardText}>{a.description}</Text> : null}
                <Text style={styles.meta}>
                  {a.app_name} · {timeAgo(a.created_at)}
                </Text>
              </View>
            </View>
          ))}
        {empty ? <EmptyState icon="inbox" title="Nothing here yet" /> : null}
      </View>
    </ScrollView>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.surfaceSecondary },
    content: { padding: space.lg, gap: space.xl },
    grid: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm + 2 },
    stat: {
      width: '47%',
      flexGrow: 1,
      backgroundColor: colors.surface,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: colors.border,
      borderRadius: radius.xxl,
      padding: space.lg,
      ...shadow.card,
    },
    statTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: space.md },
    statIcon: { width: 34, height: 34, borderRadius: radius.md + 2, alignItems: 'center', justifyContent: 'center' },
    statValue: { ...type.display, fontSize: 28, lineHeight: 32, color: colors.text },
    statLabel: { ...type.callout, color: colors.textSecondary, marginTop: 2 },
    rowCard: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md, padding: space.md + 2 },
    titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm },
    cardTitle: { flex: 1, ...type.headline, fontSize: 15, color: colors.text },
    cardText: { ...type.callout, color: colors.textSecondary },
    meta: { ...type.caption, color: colors.textTertiary, marginTop: 2 },
    timeline: { flexDirection: 'row', gap: space.md },
    rail: { width: 14, alignItems: 'center' },
    dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.brand, marginTop: 5 },
    railLine: { flex: 1, width: 2, backgroundColor: colors.border, marginTop: 4 },
  });
