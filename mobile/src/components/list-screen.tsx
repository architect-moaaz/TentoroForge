import type { Feather } from '@expo/vector-icons';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { EmptyState, LetterTile, SearchField, SkeletonList } from '@/components/kit';
import { StatusBadge } from '@/components/ui';
import { apiJson } from '@/lib/api';
import { useOrg } from '@/lib/org';
import { radius, shadow, space, type, useColors, type Palette } from '@/theme';

export interface RowInfo {
  id: string;
  title: string;
  subtitle?: string | null;
  meta?: string | null;
  badge?: string | null;
}

/** A pull-to-refresh list of cards for one organisation endpoint.
 *  `path` gets the org id; `toRow` turns each JSON item into a card. */
export function ListScreen<T>({
  path,
  select,
  toRow,
  onPressRow,
  searchPlaceholder,
  emptyTitle,
  emptyText,
  icon = 'inbox',
}: {
  path: (orgId: string) => string;
  /** Picks the array out of a response that wraps it (for example `{ templates }`). */
  select?: (body: any) => T[];
  toRow: (item: T) => RowInfo;
  onPressRow?: (row: RowInfo) => void;
  searchPlaceholder?: string;
  emptyTitle: string;
  emptyText: string;
  icon?: React.ComponentProps<typeof Feather>['name'];
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const insets = useSafeAreaInsets();
  const { org } = useOrg();
  const [rows, setRows] = useState<RowInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    if (!org) return;
    setError(null);
    try {
      const body = await apiJson<any>(path(org.id));
      const items: T[] = select ? select(body) : body;
      setRows(items.map(toRow));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load this list');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
    // path/select/toRow are fresh closures each render; the org is the real input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org?.id]);

  useEffect(() => {
    load();
  }, [load]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => `${r.title} ${r.subtitle ?? ''} ${r.meta ?? ''}`.toLowerCase().includes(q));
  }, [rows, query]);

  if (loading) return <SkeletonList />;

  return (
    <View style={styles.screen}>
      {searchPlaceholder ? (
        <View style={{ paddingTop: space.md }}>
          <SearchField value={query} onChangeText={setQuery} placeholder={searchPlaceholder} />
        </View>
      ) : null}
      <FlatList
        data={shown}
        keyExtractor={(r) => r.id}
        contentContainerStyle={{
          padding: space.lg,
          paddingTop: searchPlaceholder ? space.xs : space.lg,
          paddingBottom: space.xxxl + insets.bottom,
          gap: space.sm + 2,
          flexGrow: 1,
        }}
        refreshing={refreshing}
        onRefresh={() => {
          setRefreshing(true);
          load();
        }}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        ListHeaderComponent={
          !error && shown.length > 0 ? (
            <Text style={styles.count}>
              {shown.length} {shown.length === 1 ? 'ITEM' : 'ITEMS'}
            </Text>
          ) : undefined
        }
        ListEmptyComponent={
          error ? (
            <EmptyState icon="alert-circle" tone="error" title="Could not load" text={error} action={{ label: 'Try again', onPress: load }} />
          ) : query ? (
            <EmptyState icon="search" title="No matches" text="Try a different search." />
          ) : (
            <EmptyState icon={icon} title={emptyTitle} text={emptyText} />
          )
        }
        renderItem={({ item }) => (
          <Pressable
            disabled={!onPressRow}
            onPress={() => onPressRow?.(item)}
            style={({ pressed }) => [styles.card, pressed && { backgroundColor: colors.muted }]}>
            <LetterTile name={item.title} size={40} />
            <View style={{ flex: 1, gap: 2 }}>
              <View style={styles.head}>
                <Text style={styles.title} numberOfLines={1}>
                  {item.title}
                </Text>
                {item.badge ? <StatusBadge status={item.badge} /> : null}
              </View>
              {item.subtitle ? (
                <Text style={styles.subtitle} numberOfLines={2}>
                  {item.subtitle}
                </Text>
              ) : null}
              {item.meta ? (
                <Text style={styles.meta} numberOfLines={1}>
                  {item.meta}
                </Text>
              ) : null}
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.surfaceSecondary },
    count: { ...type.label, color: colors.textTertiary, marginBottom: space.xs, paddingLeft: space.xs },
    card: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: space.md,
      backgroundColor: colors.surface,
      borderRadius: radius.xxl,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: colors.border,
      padding: space.md + 2,
      ...shadow.card,
    },
    head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm },
    title: { flex: 1, ...type.headline, fontSize: 15, color: colors.text },
    subtitle: { ...type.callout, color: colors.textSecondary },
    meta: { ...type.caption, color: colors.textTertiary, marginTop: 2 },
  });
