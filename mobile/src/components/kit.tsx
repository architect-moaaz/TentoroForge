import { Feather } from '@expo/vector-icons';
import type { ComponentProps, ReactNode } from 'react';
import { useEffect, useMemo, useState } from 'react';
import {
  Animated,
  Easing,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/ui';
import { icon, radius, shadow, space, touch, type, useColors, type Palette } from '@/theme';

// The shared building blocks every screen uses, so a card, a row or an empty
// state looks the same wherever it appears. Sizes come from the tokens in theme.ts.

type IconName = ComponentProps<typeof Feather>['name'];

function useKitStyles() {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return { colors, styles };
}

/** A rounded surface. Pass `onPress` to make the whole card tappable. */
export function Card({
  children,
  onPress,
  style,
  padded = true,
}: {
  children: ReactNode;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  padded?: boolean;
}) {
  const { styles } = useKitStyles();
  if (!onPress) return <View style={[styles.card, padded && styles.cardPad, style]}>{children}</View>;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.card, padded && styles.cardPad, pressed && styles.cardPressed, style]}>
      {children}
    </Pressable>
  );
}

/** Big page title with an optional line under it and buttons on the right. */
export function ScreenHeader({ title, subtitle, right }: { title: string; subtitle?: string | null; right?: ReactNode }) {
  const { styles } = useKitStyles();
  return (
    <View style={styles.header}>
      <View style={{ flex: 1 }}>
        <Text style={styles.display} numberOfLines={1}>
          {title}
        </Text>
        {subtitle ? <Text style={styles.headerSub}>{subtitle}</Text> : null}
      </View>
      {right ? <View style={styles.headerRight}>{right}</View> : null}
    </View>
  );
}

/** Round icon button with a full-size touch area. */
export function IconButton({ name, onPress, label }: { name: IconName; onPress: () => void; label: string }) {
  const { colors, styles } = useKitStyles();
  return (
    <Pressable
      onPress={onPress}
      accessibilityLabel={label}
      hitSlop={6}
      style={({ pressed }) => [styles.iconButton, pressed && { opacity: 0.7, transform: [{ scale: 0.92 }] }]}>
      <Feather name={name} size={icon.md} color={colors.text} />
    </Pressable>
  );
}

/** Search box with a clear button. */
export function SearchField({
  value,
  onChangeText,
  placeholder,
}: {
  value: string;
  onChangeText: (t: string) => void;
  placeholder: string;
}) {
  const { colors, styles } = useKitStyles();
  return (
    <View style={styles.search}>
      <Feather name="search" size={icon.sm + 2} color={colors.textTertiary} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.textTertiary}
        style={styles.searchInput}
        autoCorrect={false}
        autoCapitalize="none"
        returnKeyType="search"
      />
      {value ? (
        <Pressable onPress={() => onChangeText('')} hitSlop={10} accessibilityLabel="Clear search">
          <Feather name="x-circle" size={icon.sm + 2} color={colors.textTertiary} />
        </Pressable>
      ) : null}
    </View>
  );
}

/** Labelled text input with a leading icon. The border turns black (white in dark mode) while typing. */
export function TextField({
  label,
  icon: name,
  secure,
  right,
  ...input
}: ComponentProps<typeof TextInput> & { label: string; icon?: IconName; secure?: boolean; right?: ReactNode }) {
  const { colors, styles } = useKitStyles();
  const [focused, setFocused] = useState(false);
  return (
    <View style={{ gap: space.xs + 2 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={[styles.field, focused && { borderColor: colors.text, backgroundColor: colors.surface }]}>
        {name ? <Feather name={name} size={icon.sm + 2} color={focused ? colors.text : colors.textTertiary} /> : null}
        <TextInput
          {...input}
          secureTextEntry={secure}
          placeholderTextColor={colors.textTertiary}
          cursorColor={colors.text}
          selectionColor={colors.text}
          style={styles.fieldInput}
          onFocus={(e) => {
            setFocused(true);
            input.onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            input.onBlur?.(e);
          }}
        />
        {right}
      </View>
    </View>
  );
}

/** Centered icon, title and text for empty lists, errors and locked pages. */
export function EmptyState({
  icon: name,
  title,
  text,
  tone = 'neutral',
  action,
}: {
  icon: IconName;
  title: string;
  text?: string | null;
  tone?: 'neutral' | 'error';
  action?: { label: string; onPress: () => void };
}) {
  const { colors, styles } = useKitStyles();
  const error = tone === 'error';
  return (
    <View style={styles.empty}>
      <View style={[styles.emptyIcon, error && { backgroundColor: colors.dangerBg }]}>
        <Feather name={name} size={icon.lg + 4} color={error ? colors.danger : colors.textSecondary} />
      </View>
      <Text style={styles.emptyTitle}>{title}</Text>
      {text ? <Text style={styles.emptyText}>{text}</Text> : null}
      {action ? <Button label={action.label} tone="outline" onPress={action.onPress} style={{ marginTop: space.sm }} /> : null}
    </View>
  );
}

/** Pill tabs: a grey track with the chosen one raised in white. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string; icon?: IconName }[];
  value: T;
  onChange: (id: T) => void;
}) {
  const { colors, styles } = useKitStyles();
  return (
    <View style={styles.segTrack}>
      {options.map((o) => {
        const on = o.id === value;
        return (
          <Pressable key={o.id} onPress={() => onChange(o.id)} style={[styles.seg, on && styles.segOn]}>
            {o.icon ? <Feather name={o.icon} size={icon.sm} color={on ? colors.text : colors.textSecondary} /> : null}
            <Text style={[styles.segText, on && { color: colors.text }]} numberOfLines={1}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Small caps label above a group of rows. */
export function SectionLabel({ children }: { children: string }) {
  const { styles } = useKitStyles();
  return <Text style={styles.sectionLabel}>{children.toUpperCase()}</Text>;
}

/** Rows stacked inside one card with thin lines between them. */
export function RowGroup({ children }: { children: ReactNode }) {
  const { styles } = useKitStyles();
  return <View style={styles.group}>{children}</View>;
}

/** One line in a menu or list: leading icon or tile, text, then trailing content. */
export function ListRow({
  title,
  subtitle,
  leading,
  trailing,
  onPress,
  first,
  dimmed,
  chevron = !!onPress,
}: {
  title: string;
  subtitle?: string | null;
  leading?: ReactNode;
  trailing?: ReactNode;
  onPress?: () => void;
  /** First row in a RowGroup: no line above it. */
  first?: boolean;
  dimmed?: boolean;
  chevron?: boolean;
}) {
  const { colors, styles } = useKitStyles();
  return (
    <Pressable
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => [styles.row, !first && styles.rowLine, pressed && { backgroundColor: colors.muted }]}>
      {leading}
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={[styles.rowTitle, dimmed && { color: colors.textTertiary }]} numberOfLines={1}>
          {title}
        </Text>
        {subtitle ? (
          <Text style={styles.rowSub} numberOfLines={2}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      {trailing}
      {chevron ? <Feather name="chevron-right" size={icon.md} color={colors.textTertiary} /> : null}
    </Pressable>
  );
}

/** Soft square holding an icon, used at the start of menu rows. */
export function IconTile({ name, tint, size = 34 }: { name: IconName; tint?: string; size?: number }) {
  const colors = useColors();
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: radius.md + 2,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: tint ? `${tint}1f` : colors.muted,
      }}>
      <Feather name={name} size={size * 0.5} color={tint ?? colors.text} />
    </View>
  );
}

// Tile colours for letter squares. The name picks one, so a project keeps its colour.
const TILE_COLORS = ['#6172f3', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'];

export function tileColor(name: string): string {
  let sum = 0;
  for (const ch of name) sum = (sum * 31 + ch.charCodeAt(0)) >>> 0;
  return TILE_COLORS[sum % TILE_COLORS.length];
}

/** Coloured square with the first letter of a name. */
export function LetterTile({ name, size = 44 }: { name: string; size?: number }) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: radius.lg + 2,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: tileColor(name),
      }}>
      <Text style={{ ...type.headline, fontSize: size * 0.4, lineHeight: size * 0.5, color: '#fff' }}>
        {name.trim().charAt(0).toUpperCase() || '?'}
      </Text>
    </View>
  );
}

/** Bottom sheet: dark backdrop, rounded top, grab handle, safe-area padding. Tap outside to close. */
export function Sheet({
  visible,
  onClose,
  title,
  children,
}: {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
}) {
  const { styles } = useKitStyles();
  const insets = useSafeAreaInsets();
  // 0 = hidden, 1 = shown. The backdrop fades with it; the sheet rises from below.
  const [progress] = useState(() => new Animated.Value(0));
  // Stays true until the closing animation ends, so the sheet can slide away.
  const [mounted, setMounted] = useState(visible);
  if (visible && !mounted) setMounted(true);

  useEffect(() => {
    if (visible) {
      Animated.spring(progress, { toValue: 1, useNativeDriver: true, damping: 22, stiffness: 220, mass: 0.9 }).start();
    } else if (mounted) {
      Animated.timing(progress, { toValue: 0, duration: 180, easing: Easing.in(Easing.quad), useNativeDriver: true }).start(
        () => setMounted(false),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const translateY = progress.interpolate({ inputRange: [0, 1], outputRange: [500, 0] });

  return (
    <Modal visible={mounted} transparent animationType="none" statusBarTranslucent onRequestClose={onClose}>
      <View style={{ flex: 1, justifyContent: 'flex-end' }}>
        <Animated.View style={[styles.backdrop, { opacity: progress }]}>
          <Pressable style={{ flex: 1 }} onPress={onClose} accessibilityLabel="Close" />
        </Animated.View>
        <Animated.View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg, transform: [{ translateY }] }]}>
          <View style={styles.handle} />
          {title ? <Text style={styles.sheetTitle}>{title}</Text> : null}
          {children}
        </Animated.View>
      </View>
    </Modal>
  );
}

/** A grey block that gently pulses while real content loads. */
export function Skeleton({ width, height, radius: r, style }: { width?: number | `${number}%`; height: number; radius?: number; style?: StyleProp<ViewStyle> }) {
  const { styles } = useKitStyles();
  const [pulse] = useState(() => new Animated.Value(0.5));
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.5, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse]);
  return <Animated.View style={[styles.skeleton, { width: width ?? '100%', height, opacity: pulse }, r !== undefined && { borderRadius: r }, style]} />;
}

/** Placeholder cards shaped like list rows, shown on first load instead of a spinner. */
export function SkeletonList({ count = 6, padTop = space.lg }: { count?: number; padTop?: number }) {
  const { styles } = useKitStyles();
  return (
    <View style={{ paddingHorizontal: space.lg, paddingTop: padTop, gap: space.sm + 2 }}>
      {Array.from({ length: count }, (_, i) => (
        <View key={i} style={[styles.card, { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.md + 2 }]}>
          <Skeleton width={42} height={42} radius={radius.lg + 2} />
          <View style={{ flex: 1, gap: space.sm }}>
            <Skeleton width="55%" height={14} />
            <Skeleton width="80%" height={11} />
          </View>
        </View>
      ))}
    </View>
  );
}

/** "just now", "5 min ago", "3 days ago", or the date when older than a month. */
export function timeAgo(value: string | number): string {
  const ms = typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : new Date(value).getTime();
  const mins = Math.floor((Date.now() - ms) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  return new Date(ms).toLocaleDateString();
}

const makeStyles = (c: Palette) =>
  StyleSheet.create({
    card: {
      backgroundColor: c.surface,
      borderRadius: radius.xxl,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: c.border,
      ...shadow.card,
    },
    cardPad: { padding: space.lg, gap: space.xs + 2 },
    // A pressed card sinks a touch and greys, so a tap feels physical.
    cardPressed: { backgroundColor: c.muted, transform: [{ scale: 0.985 }] },
    skeleton: { backgroundColor: c.muted, borderRadius: radius.md },
    header: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      gap: space.md,
      paddingHorizontal: space.xl,
      paddingTop: space.md,
      paddingBottom: space.lg,
    },
    display: { ...type.display, color: c.text },
    headerSub: { ...type.callout, color: c.textSecondary, marginTop: 2 },
    headerRight: { flexDirection: 'row', gap: space.sm, paddingBottom: 2 },
    iconButton: {
      width: touch - 4,
      height: touch - 4,
      borderRadius: radius.pill,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: c.surface,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: c.border,
      ...shadow.card,
    },
    search: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm,
      marginHorizontal: space.lg,
      marginBottom: space.md,
      paddingHorizontal: space.md + 2,
      height: touch,
      borderRadius: radius.xl,
      backgroundColor: c.muted,
    },
    searchInput: { flex: 1, ...type.body, color: c.text, paddingVertical: 0 },
    fieldLabel: { ...type.callout, fontFamily: 'Inter_500Medium', color: c.text },
    field: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.sm + 2,
      height: touch + 6,
      paddingHorizontal: space.md + 2,
      borderRadius: radius.xl,
      borderWidth: 1.5,
      borderColor: c.border,
      backgroundColor: c.surfaceSecondary,
    },
    fieldInput: { flex: 1, height: '100%', ...type.body, color: c.text, paddingVertical: 0 },
    empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.sm, padding: space.xxl, marginTop: space.xl },
    emptyIcon: {
      width: 64,
      height: 64,
      borderRadius: radius.pill,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: c.muted,
      marginBottom: space.sm,
    },
    emptyTitle: { ...type.headline, fontSize: 17, color: c.text, textAlign: 'center' },
    emptyText: { ...type.callout, color: c.textSecondary, textAlign: 'center', maxWidth: 300 },
    segTrack: { flexDirection: 'row', backgroundColor: c.muted, borderRadius: radius.xl, padding: 3 },
    seg: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
      minHeight: touch - 8,
      borderRadius: radius.lg + 1,
      paddingHorizontal: space.sm,
    },
    segOn: { backgroundColor: c.surface, ...shadow.card },
    segText: { ...type.callout, fontFamily: 'Inter_500Medium', color: c.textSecondary },
    sectionLabel: { ...type.label, color: c.textTertiary, paddingLeft: space.xs, marginBottom: space.sm },
    group: {
      backgroundColor: c.surface,
      borderRadius: radius.xxl,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: c.border,
      overflow: 'hidden',
    },
    row: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: touch + 12, paddingHorizontal: space.lg, paddingVertical: space.md },
    rowLine: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.border },
    rowTitle: { ...type.body, fontFamily: 'Inter_500Medium', color: c.text },
    rowSub: { ...type.caption, fontSize: 13, color: c.textSecondary },
    backdrop: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(15,23,42,0.45)' },
    sheet: {
      backgroundColor: c.surfaceSecondary,
      borderTopLeftRadius: radius.xxl + 8,
      borderTopRightRadius: radius.xxl + 8,
      paddingHorizontal: space.lg,
      paddingTop: space.sm + 2,
      ...shadow.float,
    },
    handle: { alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: c.border, marginBottom: space.lg },
    sheetTitle: { ...type.title, color: c.text, marginBottom: space.lg },
  });
