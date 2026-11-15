import { Feather } from '@expo/vector-icons';
import { useMemo } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Card, EmptyState, IconTile, LetterTile, ListRow, RowGroup, SectionLabel, SkeletonList } from '@/components/kit';
import { StatusBadge } from '@/components/ui';
import { apiJson } from '@/lib/api';
import { useOrg } from '@/lib/org';
import { useOrgData } from '@/lib/use-org-data';
import { icon, radius, space, type, useColors, type Palette } from '@/theme';

interface Person {
  id: string;
  first_name: string | null;
  last_name: string | null;
  email?: string;
  title?: string | null;
}
interface Team {
  id: string;
  name: string;
  people?: Person[];
}
interface Dept {
  id: string;
  name: string;
  description?: string | null;
  teams?: Team[];
  people?: Person[];
  children?: Dept[];
}
interface Chart {
  departments: Dept[];
  unassigned_teams?: Team[];
  unassigned_people?: Person[];
}

const nameOf = (p: Person) => [p.first_name, p.last_name].filter(Boolean).join(' ') || p.email || 'Unnamed';

type Styles = ReturnType<typeof makeStyles>;

function PersonLine({ p, styles }: { p: Person; styles: Styles }) {
  const name = nameOf(p);
  return (
    <View style={styles.person}>
      <LetterTile name={name} size={26} />
      <Text style={styles.personName} numberOfLines={1}>
        {name}
        {p.title ? <Text style={styles.personTitle}> · {p.title}</Text> : null}
      </Text>
    </View>
  );
}

function DeptNode({ dept, depth, styles, colors }: { dept: Dept; depth: number; styles: Styles; colors: Palette }) {
  return (
    <View style={[{ gap: space.sm + 2 }, depth > 0 && styles.child]}>
      <Card>
        <View style={styles.head}>
          <IconTile name="briefcase" tint="#8b5cf6" size={32} />
          <Text style={styles.title}>{dept.name}</Text>
        </View>
        {dept.description ? <Text style={styles.desc}>{dept.description}</Text> : null}
        {(dept.teams ?? []).map((t) => (
          <View key={t.id} style={styles.team}>
            <View style={styles.teamHead}>
              <Feather name="user-check" size={icon.sm} color={colors.textSecondary} />
              <Text style={styles.teamName}>{t.name}</Text>
            </View>
            {(t.people ?? []).map((p) => (
              <PersonLine key={p.id} p={p} styles={styles} />
            ))}
          </View>
        ))}
        {(dept.people ?? []).map((p) => (
          <PersonLine key={p.id} p={p} styles={styles} />
        ))}
      </Card>
      {(dept.children ?? []).map((c) => (
        <DeptNode key={c.id} dept={c} depth={depth + 1} styles={styles} colors={colors} />
      ))}
    </View>
  );
}

function useScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return { colors, styles, bottom: insets.bottom };
}

/** The org chart, read-only: departments with their teams and people, nested. */
export function OrgChartScreen() {
  const { colors, styles, bottom } = useScreen();
  const { data, loading, error, refreshing, refresh, reload } = useOrgData((id) => apiJson<Chart>(`/api/orgs/${id}/org-chart`));

  if (loading) return <SkeletonList />;
  if (error || !data)
    return <EmptyState icon="alert-circle" tone="error" title="Could not load the org chart" text={error} action={{ label: 'Try again', onPress: reload }} />;

  const empty = data.departments.length === 0 && !data.unassigned_teams?.length && !data.unassigned_people?.length;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.content, { paddingBottom: space.xxxl + bottom }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}>
      {empty ? <EmptyState icon="git-merge" title="Nothing here yet" text="No departments, teams or people yet." /> : null}
      {data.departments.map((d) => (
        <DeptNode key={d.id} dept={d} depth={0} styles={styles} colors={colors} />
      ))}
      {data.unassigned_teams?.length ? (
        <Card>
          <Text style={styles.title}>Unassigned teams</Text>
          {data.unassigned_teams.map((t) => (
            <View key={t.id} style={styles.teamHead}>
              <Feather name="user-check" size={icon.sm} color={colors.textSecondary} />
              <Text style={styles.teamName}>{t.name}</Text>
            </View>
          ))}
        </Card>
      ) : null}
      {data.unassigned_people?.length ? (
        <Card>
          <Text style={styles.title}>Unassigned people</Text>
          {data.unassigned_people.map((p) => (
            <PersonLine key={p.id} p={p} styles={styles} />
          ))}
        </Card>
      ) : null}
    </ScrollView>
  );
}

interface Member {
  id: string;
  email: string;
  name: string | null;
  role: string;
  invite_status: string;
}

/** Organisation settings, read-only for now: the org and its members. */
export function SettingsScreen() {
  const { styles, bottom } = useScreen();
  const { org } = useOrg();
  const { data, loading, error, refreshing, refresh } = useOrgData((id) => apiJson<Member[]>(`/api/orgs/${id}/members`));

  if (loading) return <SkeletonList />;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.content, { paddingBottom: space.xxxl + bottom }]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}>
      <Card style={styles.orgCard}>
        <LetterTile name={org?.name ?? '?'} size={52} />
        <View style={{ flex: 1 }}>
          <Text style={styles.orgName}>{org?.name}</Text>
          <Text style={styles.desc}>/{org?.slug}</Text>
        </View>
      </Card>

      <View>
        <SectionLabel>{`Members${data ? ` · ${data.length}` : ''}`}</SectionLabel>
        {error ? (
          <EmptyState icon="alert-circle" tone="error" title="Could not load members" text={error} />
        ) : (
          <RowGroup>
            {(data ?? []).map((m, i) => (
              <ListRow
                key={m.id}
                first={i === 0}
                title={m.name || m.email}
                subtitle={m.name ? `${m.email} · ${m.role}` : m.role}
                leading={<LetterTile name={m.name || m.email} size={36} />}
                trailing={<StatusBadge status={m.invite_status} />}
              />
            ))}
          </RowGroup>
        )}
      </View>
      <Text style={styles.note}>Inviting people and changing the brand, integrations and usage are on the web app for now.</Text>
    </ScrollView>
  );
}

/** CSV import needs a file picker and a column-mapping step, which are not built yet. */
export function ImportScreen() {
  return (
    <EmptyState
      icon="upload-cloud"
      title="Import people"
      text="Importing people from a CSV file is not on mobile yet. Use the web app for now."
    />
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.surfaceSecondary },
    content: { padding: space.lg, gap: space.lg },
    child: { marginLeft: space.md, paddingLeft: space.md, borderLeftWidth: 2, borderLeftColor: colors.border },
    head: { flexDirection: 'row', alignItems: 'center', gap: space.sm + 2 },
    title: { flex: 1, ...type.headline, fontSize: 15, color: colors.text },
    desc: { ...type.callout, color: colors.textSecondary },
    team: {
      marginTop: space.xs,
      padding: space.md,
      borderRadius: radius.lg,
      backgroundColor: colors.surfaceSecondary,
      gap: space.sm,
    },
    teamHead: { flexDirection: 'row', alignItems: 'center', gap: space.xs + 2 },
    teamName: { ...type.callout, fontFamily: 'Inter_600SemiBold', color: colors.text },
    person: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
    personName: { flex: 1, ...type.callout, color: colors.text },
    personTitle: { color: colors.textSecondary },
    orgCard: { flexDirection: 'row', alignItems: 'center', gap: space.md + 2 },
    orgName: { ...type.title, color: colors.text },
    note: { ...type.caption, color: colors.textTertiary, textAlign: 'center', paddingHorizontal: space.xl },
  });
