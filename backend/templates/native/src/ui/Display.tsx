// The component kit — small things that show a fact: a status, a person, a
// label, a figure, an amount, a language switch.
//
//   <StatusBadge status={row.status} />          colour from the word (done = green, failed = red …)
//   <Badge tone="warning">Needs review</Badge>
//   <Avatar name={row.ownerName} image={row.photo} />
//   <Tag>Urgent</Tag>
//   <StatTile label="Revenue" value={formatMoney(total)} delta={0.12} />
//   <Money value={row.total} />
//   <LanguageSwitch />                           nothing when the app has one language

import * as React from "react";
import { Image, Pressable, View, ScrollView } from "react-native";
import { useTheme } from "../theme";
import { Text, type TextProps } from "./Text";
import { Card } from "./Layout";
import { fileSource } from "../sdk/files";
import { formatMoney } from "../sdk/money";
import { useLanguage } from "../sdk/i18n";
import { deltaText, initials, statusTone, type Tone } from "./logic";

export type { Tone };

function toneColors(theme: ReturnType<typeof useTheme>, tone: Tone): { bg: string; fg: string } {
  const c = theme.colors;
  switch (tone) {
    case "info": return { bg: c.infoSubtle, fg: c.infoSubtleForeground };
    case "success": return { bg: c.successSubtle, fg: c.successSubtleForeground };
    case "warning": return { bg: c.warningSubtle, fg: c.warningSubtleForeground };
    case "danger": return { bg: c.destructiveSubtle, fg: c.destructiveSubtleForeground };
    case "accent": return { bg: c.accentSubtle, fg: c.accentSubtleForeground };
    default: return { bg: c.secondary, fg: c.secondaryForeground };
  }
}

export function Badge({ children, tone = "neutral", dot = false }: { children: React.ReactNode; tone?: Tone; dot?: boolean }) {
  const theme = useTheme();
  const t = toneColors(theme, tone);
  return (
    <View style={{ alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: t.bg, borderRadius: theme.radiusPill, paddingHorizontal: 10, paddingVertical: 4 }}>
      {dot ? <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: t.fg }} /> : null}
      {typeof children === "string"
        ? <Text variant="caption" weight="semibold" style={{ color: t.fg }}>{children}</Text>
        : children}
    </View>
  );
}

/** "in_progress" -> a blue "In progress". The word is shown as a person says it. */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = String(status ?? "");
  const label = s.replace(/[_-]+/g, " ").replace(/^./, (ch) => ch.toUpperCase());
  return <Badge tone={statusTone(s)} dot>{label || "—"}</Badge>;
}

/** A value out of a few, as dots: priority 3 of 5 is three filled and two quiet. `max` defaults to 5. */
export function Dots({ value, max = 5, label }: { value: number | null | undefined; max?: number; label?: string }) {
  const theme = useTheme();
  const n = Math.max(0, Math.min(max, Math.round(value ?? 0)));
  return (
    <View accessibilityRole="image" accessibilityLabel={label ?? (n ? `${n} of ${max}` : "Not set")} style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      {Array.from({ length: max }, (_, i) => (
        <View key={i} style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: i < n ? theme.colors.accent : theme.colors.muted }} />
      ))}
    </View>
  );
}

export interface ChipItem<K extends string = string> {
  key: K;
  label: string;
  /** A number after the label ("Scheduled 3"). */
  count?: number;
}

/** A row of filter chips that scrolls sideways instead of wrapping onto a second line, reaching the screen's
 *  edges. One is selected; pressing another calls `onChange` with its key.
 *
 *    <Chips items={[{ key: "all", label: "All", count: 12 }, …]} value={tab} onChange={setTab} />  */
export function Chips<K extends string>({ items, value, onChange }: { items: ChipItem<K>[]; value: K; onChange: (key: K) => void }) {
  const theme = useTheme();
  const c = theme.colors;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -theme.space.lg }}
      contentContainerStyle={{ paddingHorizontal: theme.space.lg, gap: theme.space.sm }} accessibilityRole="tablist">
      {items.map((it) => {
        const on = it.key === value;
        return (
          <Pressable key={it.key} onPress={() => onChange(it.key)} accessibilityRole="tab" accessibilityState={{ selected: on }}
            accessibilityLabel={it.count === undefined ? it.label : `${it.label}, ${it.count}`}
            hitSlop={{ top: 6, bottom: 6 }}
            style={({ pressed }) => ({
              flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, height: 36, borderRadius: theme.radiusPill,
              backgroundColor: on ? c.primary : c.card, borderWidth: theme.borderWidth, borderColor: on ? c.primary : c.border, opacity: pressed ? 0.85 : 1,
            })}>
            <Text variant="label" style={{ color: on ? c.primaryForeground : c.foreground }}>{it.label}</Text>
            {it.count !== undefined ? (
              <View style={{ minWidth: 20, paddingHorizontal: 6, borderRadius: 10, alignItems: "center", backgroundColor: on ? theme.alpha("primaryForeground", 0.22) : c.muted }}>
                <Text variant="caption" weight="semibold" style={{ color: on ? c.primaryForeground : c.mutedForeground }}>{it.count}</Text>
              </View>
            ) : null}
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

/** A quiet outlined label: a category, a filter chip; `onPress` makes it a toggle. */
export function Tag({ children, onPress, selected }: { children: string; onPress?: () => void; selected?: boolean }) {
  const theme = useTheme();
  const c = theme.colors;
  const body = (
    <View style={{ borderRadius: theme.radiusPill, borderWidth: theme.borderWidth, borderColor: selected ? c.primary : c.border,
                   backgroundColor: selected ? c.primary : "transparent", paddingHorizontal: 12, paddingVertical: 5 }}>
      <Text variant="caption" weight="medium" style={{ color: selected ? c.primaryForeground : c.foreground }}>{children}</Text>
    </View>
  );
  if (!onPress) return body;
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={children} accessibilityState={{ selected: Boolean(selected) }}
      hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}>
      {body}
    </Pressable>
  );
}

/** A person: their picture (a stored file's id or a URL) or their initials. */
export function Avatar({ name, image, size = 40 }: { name?: string | null; image?: string | null; size?: number }) {
  const theme = useTheme();
  const src = fileSource(image);
  const round = { width: size, height: size, borderRadius: size / 2 };
  if (src) return <Image source={src} accessibilityLabel={name ?? "Avatar"} style={[round, { backgroundColor: theme.colors.muted }]} />;
  return (
    <View accessibilityRole="image" accessibilityLabel={name ?? "Avatar"} style={[round, { backgroundColor: theme.colors.accentSubtle, alignItems: "center", justifyContent: "center" }]}>
      <Text weight="semibold" style={{ color: theme.colors.accentSubtleForeground, fontSize: Math.max(11, size * 0.38) }}>{initials(name)}</Text>
    </View>
  );
}

/** A headline figure: what it measures, the number, and — over a period — how
 *  it changed (0.12 = up 12%). `value` is shown as given: format it first. */
export function StatTile({ label, value, delta, hint }: { label: string; value: string | number | null | undefined; delta?: number | null; hint?: string }) {
  const theme = useTheme();
  const d = deltaText(delta);
  const shown = value === null || value === undefined || value === "" ? "—" : String(value);
  return (
    <Card padding="md" accessibilityLabel={`${label}: ${shown}${d ? `, ${d.text}` : ""}`} style={{ flex: 1, minWidth: 140, gap: theme.space.xs }}>
      <Text variant="caption" tone="muted">{label}</Text>
      <Text variant="display" style={{ fontSize: 28, lineHeight: 34 }}>{shown}</Text>
      {d ? <Text variant="caption" weight="semibold" tone={d.direction === "up" ? "success" : d.direction === "down" ? "danger" : "muted"}>{d.text}</Text> : null}
      {hint ? <Text variant="caption" tone="muted">{hint}</Text> : null}
    </Card>
  );
}

/** An amount in the app's currency (or the record's own): `<Money value={row.total} />`. */
export function Money({ value, currency, ...rest }: Omit<TextProps, "children"> & { value: number | null | undefined; currency?: string }) {
  return <Text {...rest} style={[{ fontVariant: ["tabular-nums"] }, rest.style]}>{value === null || value === undefined ? "—" : formatMoney(value, currency)}</Text>;
}

/** The app's one language switch. Nothing when there is one language. */
export function LanguageSwitch() {
  const { lang, setLang, languages } = useLanguage();
  if (languages.length < 2) return null;
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel="Language" style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {languages.map((l) => <Tag key={l.tag} selected={l.tag === lang} onPress={() => setLang(l.tag)}>{l.tag.toUpperCase()}</Tag>)}
    </View>
  );
}
