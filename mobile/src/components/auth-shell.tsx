import { Feather } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { API_BASE } from '@/lib/config';
import { icon, radius, space, type, useColors } from '@/theme';

// The deep-violet brand band behind the sign-in and sign-up forms.
// Fixed colours: it looks the same in light and dark mode on purpose.
const HERO = ['#2b0d55', '#1b0838'] as const;

/** Sign-in and sign-up frame: violet hero with the logo and title, then a white sheet holding the form. */
export function AuthShell({
  title,
  subtitle,
  onBack,
  children,
}: {
  title: string;
  subtitle: string;
  onBack?: () => void;
  children: ReactNode;
}) {
  const colors = useColors();
  const insets = useSafeAreaInsets();

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: HERO[1] }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ flexGrow: 1 }}
        keyboardShouldPersistTaps="handled"
        bounces={false}>
        <LinearGradient colors={HERO} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={[styles.hero, { paddingTop: insets.top + space.xl }]}>
          {/* Nested rounded squares: a quiet echo of the logo. */}
          <View style={[styles.ring, { width: 260, height: 260, top: -70, right: -80 }]} />
          <View style={[styles.ring, { width: 180, height: 180, top: -30, right: -40 }]} />
          <View style={[styles.ring, { width: 100, height: 100, top: 10, right: 0 }]} />

          {onBack ? (
            <Pressable onPress={onBack} hitSlop={12} accessibilityLabel="Back" style={styles.back}>
              <Feather name="arrow-left" size={20} color="#fff" />
            </Pressable>
          ) : null}

          <View style={styles.logo}>
            <Feather name="layers" size={24} color="#fff" />
          </View>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </LinearGradient>

        <View style={[styles.sheet, { backgroundColor: colors.surface, paddingBottom: insets.bottom + space.lg }]}>
          {children}
          <View style={styles.server}>
            <View style={[styles.dot, { backgroundColor: colors.success }]} />
            <Text style={[type.caption, { color: colors.textTertiary }]} numberOfLines={1}>
              Connected to {API_BASE.replace(/^https?:\/\//, '')}
            </Text>
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

/** "or" between two thin lines. */
export function OrDivider() {
  const colors = useColors();
  return (
    <View style={styles.divider}>
      <View style={[styles.line, { backgroundColor: colors.border }]} />
      <Text style={[type.callout, { color: colors.textTertiary }]}>or</Text>
      <View style={[styles.line, { backgroundColor: colors.border }]} />
    </View>
  );
}

/** "New to Tentoro? Create an account" style line with a bold tappable part. */
export function SwitchLine({ prompt, action, onPress }: { prompt: string; action: string; onPress: () => void }) {
  const colors = useColors();
  return (
    <Pressable onPress={onPress} hitSlop={8} style={{ alignSelf: 'center', paddingVertical: space.xs }}>
      <Text style={[type.body, { color: colors.textSecondary }]}>
        {prompt} <Text style={{ fontFamily: 'Inter_600SemiBold', color: colors.text }}>{action}</Text>
      </Text>
    </Pressable>
  );
}

export function EyeToggle({ shown, onToggle }: { shown: boolean; onToggle: () => void }) {
  const colors = useColors();
  return (
    <Pressable onPress={onToggle} hitSlop={10} accessibilityLabel={shown ? 'Hide password' : 'Show password'}>
      <Feather name={shown ? 'eye-off' : 'eye'} size={icon.md} color={colors.textSecondary} />
    </Pressable>
  );
}

export function ErrorBox({ text }: { text: string }) {
  const colors = useColors();
  return (
    <View style={[styles.errorBox, { backgroundColor: colors.dangerBg }]}>
      <Feather name="alert-circle" size={icon.sm + 2} color={colors.danger} style={{ marginTop: 2 }} />
      <Text style={[styles.errorText, { color: colors.danger }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  hero: { paddingHorizontal: space.xxl, paddingBottom: space.xxxl + 24, overflow: 'hidden' },
  ring: {
    position: 'absolute',
    borderRadius: 56,
    borderWidth: 1.5,
    borderColor: 'rgba(255,255,255,0.08)',
  },
  back: { width: 36, height: 36, justifyContent: 'center', marginBottom: space.md },
  logo: {
    width: 52,
    height: 52,
    borderRadius: radius.xl,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.12)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    marginTop: space.xxl,
    marginBottom: space.xl + 4,
  },
  title: { ...type.display, fontSize: 34, lineHeight: 40, color: '#fff' },
  subtitle: { ...type.body, color: 'rgba(255,255,255,0.72)', marginTop: space.sm },
  sheet: {
    flex: 1,
    marginTop: -28,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    paddingHorizontal: space.xxl,
    paddingTop: space.xxl + 4,
    gap: space.xl,
  },
  server: {
    marginTop: 'auto',
    paddingTop: space.xxl,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.xs + 2,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
  divider: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  line: { flex: 1, height: StyleSheet.hairlineWidth },
  errorBox: { flexDirection: 'row', gap: space.sm + 2, padding: space.md, borderRadius: radius.lg },
  errorText: { flex: 1, ...type.callout },
});
