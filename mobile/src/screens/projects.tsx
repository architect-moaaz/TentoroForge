import { Feather } from '@expo/vector-icons';
import { useRouter, type Href } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { FlatList, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Card, EmptyState, LetterTile, SearchField, Segmented, SkeletonList, timeAgo } from '@/components/kit';
import { StatusBadge } from '@/components/ui';
import { apiJson } from '@/lib/api';
import { useOrg } from '@/lib/org';
import { icon, space, type, useColors, type Palette } from '@/theme';

interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  org_id: string;
  updated_at: string;
}

type Filter = 'all' | 'ready' | 'draft';

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'ready', label: 'Ready' },
  { id: 'draft', label: 'Draft' },
];

/** The projects of the current organisation. */
export function ProjectsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { org } = useOrg();
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [rows, setRows] = useState<Project[]>([]);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!org) return;
    setError(null);
    try {
      const projects = await apiJson<Project[]>(`/api/orgs/${org.id}/projects`);
      setRows(projects.sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load projects');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [org]);

  useEffect(() => {
    load();
  }, [load]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (filter === 'all' || (filter === 'ready' ? r.status === 'ready' : r.status !== 'ready')) &&
        (!q || r.name.toLowerCase().includes(q)),
    );
  }, [rows, query, filter]);

  if (loading) return <SkeletonList />;

  return (
    <View style={styles.screen}>
      <View style={{ paddingTop: space.md }}>
        <SearchField value={query} onChangeText={setQuery} placeholder="Search projects" />
        <View style={{ paddingHorizontal: space.lg, paddingBottom: space.md }}>
          <Segmented options={FILTERS} value={filter} onChange={setFilter} />
        </View>
      </View>

      <FlatList
        data={shown}
        keyExtractor={(p) => p.id}
        contentContainerStyle={{ paddingHorizontal: space.lg, paddingBottom: space.xxxl + insets.bottom, gap: space.md - 2, flexGrow: 1 }}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        refreshing={refreshing}
        onRefresh={() => {
          setRefreshing(true);
          load();
        }}
        ListHeaderComponent={
          !error && shown.length > 0 ? (
            <Text style={styles.count}>
              {shown.length} {shown.length === 1 ? 'PROJECT' : 'PROJECTS'}
            </Text>
          ) : undefined
        }
        ListEmptyComponent={
          error ? (
            <EmptyState icon="alert-circle" tone="error" title="Could not load projects" text={error} action={{ label: 'Try again', onPress: load }} />
          ) : query || filter !== 'all' ? (
            <EmptyState icon="search" title="No matches" text="Try a different search or filter." />
          ) : (
            <EmptyState icon="folder" title="No projects yet" text="Create one on the web app and it will show up here." />
          )
        }
        renderItem={({ item }) => (
          <Card
            padded={false}
            style={styles.card}
            onPress={() =>
              // The typed-route list is rebuilt when Expo starts, so a route
              // added in this session is not in it yet; hence the cast.
              router.push(`/project/${item.id}?name=${encodeURIComponent(item.name)}` as Href)
            }>
            <LetterTile name={item.name} />
            <View style={styles.body}>
              <View style={styles.titleRow}>
                <Text style={styles.name} numberOfLines={1}>
                  {item.name}
                </Text>
                <StatusBadge status={item.status} />
              </View>
              {item.description ? (
                <Text style={styles.desc} numberOfLines={1}>
                  {item.description}
                </Text>
              ) : null}
              <View style={styles.metaRow}>
                <Feather name="clock" size={icon.sm - 2} color={colors.textTertiary} />
                <Text style={styles.meta}>Updated {timeAgo(item.updated_at)}</Text>
              </View>
            </View>
          </Card>
        )}
      />
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.surfaceSecondary },
    count: { ...type.label, color: colors.textTertiary, marginBottom: space.xs, paddingLeft: space.xs },
    card: { flexDirection: 'row', alignItems: 'center', gap: space.md + 2, padding: space.md + 2 },
    body: { flex: 1, gap: 3 },
    titleRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
    name: { flex: 1, ...type.headline, color: colors.text },
    desc: { ...type.callout, color: colors.textSecondary },
    metaRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 1 },
    meta: { ...type.caption, color: colors.textTertiary },
  });
