import { Feather } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { font, radius, statusStyle, useColors } from '@/theme';

/** The Tentoro Forge mark: rounded square with stacked layers. */
export function Logo({ size = 32 }: { size?: number }) {
  const colors = useColors();
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: radius.lg,
        backgroundColor: colors.primary,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
      <Feather name="layers" size={size * 0.5} color={colors.primaryText} />
    </View>
  );
}

export function Button({
  label,
  onPress,
  busy,
  disabled,
  icon,
  tone = 'primary',
  style,
}: {
  label: string;
  onPress: () => void;
  busy?: boolean;
  disabled?: boolean;
  /** Called with the text colour so the icon matches the button. */
  icon?: (color: string) => ReactNode;
  tone?: 'primary' | 'outline' | 'danger' | 'success';
  style?: StyleProp<ViewStyle>;
}) {
  const colors = useColors();
  const bg = { primary: colors.primary, outline: colors.surface, danger: '#dc2626', success: '#16a34a' }[tone];
  const fg = tone === 'primary' ? colors.primaryText : tone === 'outline' ? colors.text : '#fff';
  return (
    <Pressable
      onPress={onPress}
      disabled={busy || disabled}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: bg, opacity: busy || disabled ? 0.5 : pressed ? 0.88 : 1 },
        pressed && !busy && !disabled && { transform: [{ scale: 0.98 }] },
        tone === 'outline' && { borderWidth: 1, borderColor: colors.border },
        style,
      ]}>
      {busy ? <ActivityIndicator color={fg} /> : null}
      <Text style={[styles.buttonText, { color: fg }]}>{busy ? '' : label}</Text>
      {!busy && icon ? icon(fg) : null}
    </Pressable>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const colors = useColors();
  const s = statusStyle(colors, status);
  return (
    <View style={[styles.badge, { backgroundColor: s.bg }]}>
      <Text style={[styles.badgeText, { color: s.fg }]}>{status}</Text>
    </View>
  );
}

/** Round-cornered avatar like the web chat: primary for you, violet gradient for Smith. */
export function Avatar({ who, size = 32 }: { who: 'user' | 'smith'; size?: number }) {
  const colors = useColors();
  const box = {
    width: size,
    height: size,
    borderRadius: radius.xl - 2,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
  };
  if (who === 'user') {
    return (
      <View style={[box, { backgroundColor: colors.primary }]}>
        <Feather name="user" size={size * 0.5} color={colors.primaryText} />
      </View>
    );
  }
  return (
    <LinearGradient colors={[colors.violet, colors.purple]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={box}>
      <Feather name="cpu" size={size * 0.5} color="#fff" />
    </LinearGradient>
  );
}

export function Field({ children }: { children: ReactNode }) {
  return <View style={{ gap: 6 }}>{children}</View>;
}

const styles =
  StyleSheet.create({
    button: {
      minHeight: 48,
      borderRadius: radius.xl,
      paddingHorizontal: 18,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
    },
    buttonText: { fontFamily: font.semibold, fontSize: 15 },
    badge: { alignSelf: 'flex-start', borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 2 },
    badgeText: { fontFamily: font.medium, fontSize: 11 },
  });
