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
import { Image, Pressable, View } from "react-native";
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

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: Tone }) {
  const theme = useTheme();
  const t = toneColors(theme, tone);
  return (
    <View style={{ alignSelf: "flex-start", backgroundColor: t.bg, borderRadius: theme.radiusPill, paddingHorizontal: 10, paddingVertical: 3 }}>
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
  return <Badge tone={statusTone(s)}>{label || "—"}</Badge>;
}

/** A quiet outlined label: a category, a filter chip; `onPress` makes it a toggle. */
export function Tag({ children, onPress, selected }: { children: string; onPress?: () => void; selected?: boolean }) {
  const theme = useTheme();
  const c = theme.colors;
  const body = (
    <View style={{ borderRadius: theme.radiusPill, borderWidth: 1, borderColor: selected ? c.primary : c.border,
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
