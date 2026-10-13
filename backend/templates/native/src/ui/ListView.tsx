// The component kit — lists. `ListView` is a FlatList that already knows the
// three states, pull-to-refresh and the next page; `ListItem` is the row most
// lists are made of.
//
//   const orders = useList("Order", { sort: "placedAt", order: "desc" });
//   <Screen title="Orders" scroll={false}>
//     <ListView list={orders} empty={<Empty title="No orders yet" />}
//       renderItem={(o) => (
//         <ListItem title={o.number} subtitle={formatDate(o.placedAt)} meta={formatMoney(o.total)}
//                   badge={<StatusBadge status={o.status} />} onPress={() => nav.push(href(pages.order, { id: o.id }))} />
//       )} />
//   </Screen>
//
// `list` is what `useList` returns (or any read of an array): `data`, `loading`,
// `error`, `refetch`, `refreshing`, and — for a paged list — `loadMore`,
// `loadingMore`. Rows are keyed by `id` unless `keyExtractor` says otherwise.

import * as React from "react";
import { ActivityIndicator, FlatList, Pressable, RefreshControl, View } from "react-native";
import { useTheme } from "../theme";
import { Text } from "./Text";
import { Divider } from "./Layout";
import { ErrorState, Loading } from "./States";

export interface ListLike<T> {
  data: T[] | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  loadMore?: () => Promise<void>;
  loadingMore?: boolean;
}

export interface ListViewProps<T> {
  list: ListLike<T>;
  renderItem: (item: T, index: number) => React.ReactElement | null;
  keyExtractor?: (item: T, index: number) => string;
  /** Shown when there are no rows: `<Empty … />`. */
  empty?: React.ReactNode;
  /** Above the rows, scrolling with them (a search box, a summary). */
  header?: React.ReactNode;
  /** Hairlines between rows (default true). */
  separators?: boolean;
}

export function ListView<T>({ list, renderItem, keyExtractor, empty, header, separators = true }: ListViewProps<T>) {
  const theme = useTheme();
  if (list.loading) return <Loading />;
  if (list.error && !list.data) return <ErrorState message={list.error} onRetry={() => { void list.refetch(); }} />;
  const rows = list.data ?? [];
  return (
    <FlatList
      data={rows}
      keyExtractor={keyExtractor ?? ((item, i) => String((item as { id?: unknown }).id ?? i))}
      renderItem={({ item, index }) => renderItem(item, index)}
      ItemSeparatorComponent={separators ? () => <Divider /> : undefined}
      ListHeaderComponent={header ? <View>{header}{list.error ? <Text tone="danger" style={{ paddingVertical: theme.space.sm }}>{list.error}</Text> : null}</View> : undefined}
      ListEmptyComponent={empty ? <View>{empty}</View> : undefined}
      ListFooterComponent={list.loadingMore ? <View style={{ padding: theme.space.lg }}><ActivityIndicator color={theme.colors.primary} /></View> : null}
      onEndReached={list.loadMore ? () => { void list.loadMore?.(); } : undefined}
      onEndReachedThreshold={0.4}
      refreshControl={<RefreshControl refreshing={list.refreshing} onRefresh={() => { void list.refetch(); }} tintColor={theme.colors.primary} colors={[theme.colors.primary]} />}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={rows.length ? undefined : { flexGrow: 1 }}
    />
  );
}

export interface ListItemProps {
  title: string;
  subtitle?: string;
  /** A figure or short fact on the right ("$12.50", "2 days"). */
  meta?: string;
  /** Something at the left: an `<Avatar />`, an icon. */
  leading?: React.ReactNode;
  /** Something under the text: a `<StatusBadge />`, tags. */
  badge?: React.ReactNode;
  /** Something at the right edge instead of `meta`: a switch, a chevron. */
  trailing?: React.ReactNode;
  onPress?: () => void;
}

export function ListItem({ title, subtitle, meta, leading, badge, trailing, onPress }: ListItemProps) {
  const theme = useTheme();
  const body = (
    <View style={{ flexDirection: "row", alignItems: "center", gap: theme.space.md, paddingVertical: theme.space.md, minHeight: theme.touch + 12 }}>
      {leading}
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="label" numberOfLines={1} style={{ fontSize: 16 }}>{title}</Text>
        {subtitle ? <Text variant="caption" tone="muted" numberOfLines={2}>{subtitle}</Text> : null}
        {badge ? <View style={{ marginTop: theme.space.xs }}>{badge}</View> : null}
      </View>
      {trailing ?? (meta ? <Text variant="label" tone="muted" style={{ fontVariant: ["tabular-nums"] }}>{meta}</Text> : null)}
      {onPress && !trailing ? <Text tone="muted" style={{ fontSize: 22 }} accessibilityElementsHidden importantForAccessibility="no">›</Text> : null}
    </View>
  );
  if (!onPress) return body;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={[title, subtitle, meta].filter(Boolean).join(", ")}
      style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}>
      {body}
    </Pressable>
  );
}
