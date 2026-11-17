import { Feather } from '@expo/vector-icons';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { LetterTile, ListRow, RowGroup, SectionLabel, Sheet } from '@/components/kit';
import { apiJson } from '@/lib/api';
import { useOrg } from '@/lib/org';
import { useThemePref, type ThemePref } from '@/theme-pref';
import { icon, radius, shadow, space, type, useColors, type Palette } from '@/theme';

const OPTIONS: { id: ThemePref; label: string; icon: 'smartphone' | 'sun' | 'moon' }[] = [
  { id: 'system', label: 'System', icon: 'smartphone' },
  { id: 'light', label: 'Light', icon: 'sun' },
  { id: 'dark', label: 'Dark', icon: 'moon' },
];

interface Me {
  name: string;
  email: string;
}

/** A bottom sheet with who is signed in, the organisation, the appearance choice and sign out. */
export function SettingsSheet({
  visible,
  onClose,
  onSignOut,
}: {
  visible: boolean;
  onClose: () => void;
  onSignOut: () => void;
}) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const { pref, setPref } = useThemePref();
  const { org, orgs, setOrgId } = useOrg();
  const [me, setMe] = useState<Me | null>(null);

  // Who is signed in; loaded the first time the sheet opens. A failure just hides the card.
  useEffect(() => {
    if (visible && !me) apiJson<Me>('/api/auth/me').then(setMe).catch(() => {});
  }, [visible, me]);

  return (
    <Sheet visible={visible} onClose={onClose} title="Settings">
      <View style={{ gap: space.xl }}>
        {me ? (
          <View style={styles.profile}>
            <LetterTile name={me.name || me.email} size={48} />
            <View style={{ flex: 1 }}>
              <Text style={styles.profileName} numberOfLines={1}>
                {me.name || me.email}
              </Text>
              <Text style={styles.profileEmail} numberOfLines={1}>
                {me.email}
              </Text>
            </View>
          </View>
        ) : null}

        {orgs.length > 1 ? (
          <View>
            <SectionLabel>Organisation</SectionLabel>
            <RowGroup>
              {orgs.map((o, i) => (
                <ListRow
                  key={o.id}
                  first={i === 0}
                  title={o.name}
                  subtitle={`/${o.slug}`}
                  onPress={() => setOrgId(o.id)}
                  chevron={false}
                  leading={<LetterTile name={o.name} size={34} />}
                  trailing={org?.id === o.id ? <Feather name="check-circle" size={icon.md} color={colors.brand} /> : null}
                />
              ))}
            </RowGroup>
          </View>
        ) : null}

        <View>
          <SectionLabel>Appearance</SectionLabel>
          <View style={styles.themes}>
            {OPTIONS.map((o) => {
              const on = pref === o.id;
              return (
                <Pressable
                  key={o.id}
                  onPress={() => setPref(o.id)}
                  accessibilityState={{ selected: on }}
                  style={[styles.theme, on && styles.themeOn]}>
                  <View style={[styles.themeIcon, on && { backgroundColor: colors.brandSoft }]}>
                    <Feather name={o.icon} size={icon.md} color={on ? colors.brand : colors.textSecondary} />
                  </View>
                  <Text style={[styles.themeLabel, on && { color: colors.text }]}>{o.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <Pressable
          onPress={() => {
            onClose();
            onSignOut();
          }}
          style={({ pressed }) => [styles.signOut, pressed && { opacity: 0.7 }]}>
          <Feather name="log-out" size={icon.md - 2} color={colors.danger} />
          <Text style={styles.signOutText}>Sign out</Text>
        </Pressable>
      </View>
    </Sheet>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    profile: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: space.md + 2,
      padding: space.lg,
      borderRadius: radius.xxl,
      backgroundColor: colors.surface,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: colors.border,
      ...shadow.card,
    },
    profileName: { ...type.headline, color: colors.text },
    profileEmail: { ...type.callout, color: colors.textSecondary },
    themes: { flexDirection: 'row', gap: space.sm + 2 },
    theme: {
      flex: 1,
      alignItems: 'center',
      gap: space.sm,
      paddingVertical: space.lg,
      borderRadius: radius.xl + 2,
      backgroundColor: colors.surface,
      borderWidth: 1.5,
      borderColor: colors.border,
    },
    themeOn: { borderColor: colors.brand, ...shadow.card },
    themeIcon: {
      width: 40,
      height: 40,
      borderRadius: radius.pill,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: colors.muted,
    },
    themeLabel: { ...type.callout, fontFamily: 'Inter_500Medium', color: colors.textSecondary },
    signOut: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: space.sm,
      height: 52,
      borderRadius: radius.xl,
      backgroundColor: colors.dangerBg,
    },
    signOutText: { ...type.body, fontFamily: 'Inter_600SemiBold', color: colors.danger },
  });
