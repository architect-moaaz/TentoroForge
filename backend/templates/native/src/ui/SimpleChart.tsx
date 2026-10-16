// The component kit — a small chart drawn with Views, so the kit carries no SVG
// or charting dependency. Three kinds, enough for a phone's dashboard:
//
//   bar   columns (rows, horizontal, when there are many or the labels are long)
//   line  points joined by segments, over the axis labels
//   pie   a stacked proportion bar with a legend of shares — a pie's job (parts
//         of a whole) without angles, which Views cannot draw; `donut` is the same
//
//   <SimpleChart type="bar" data={rows.map((r) => ({ label: r.month, value: r.revenue }))} format="currency" />
//   <SimpleChart type="line" labels={["Jan", "Feb"]} series={[{ name: "Sales", values: [3, 5] }]} />
//
// `data` is one series of `{ label, value }`; `labels` + `series` is several (a
// bar chart groups them, a line chart draws one line each). `format` is how a
// value reads: number, currency (the app's), percent (0.12 = 12%). The kit never
// draws a chart it cannot read back: each one is labelled for screen readers
// with its first values.

import * as React from "react";
import { View } from "react-native";
import { useTheme } from "../theme";
import { Text } from "./Text";
import { CURRENCY } from "../sdk/money";
import { LOCALE } from "../config.generated";
import { formatCell, formatCompact, type Format } from "../sdk/format";
import { axisMax, barHeight, linePoints, shares, type ChartSeries } from "./logic";

export interface ChartPoint { label: string; value: number }

export interface SimpleChartProps {
  type: "bar" | "line" | "pie" | "donut";
  data?: ChartPoint[];
  labels?: string[];
  series?: ChartSeries[];
  format?: Format;
  /** Plot height in points (default 180). */
  height?: number;
  /** Bars as rows, label on the left. Default: when there are more than 6 or the labels are long. */
  horizontal?: boolean;
}

function useColors(): string[] {
  const c = useTheme().colors;
  return [c.primary, c.accent, c.info, c.success, c.warning, c.destructive];
}

export function SimpleChart({ type, data, labels, series, format = "number", height = 180, horizontal }: SimpleChartProps) {
  const theme = useTheme();
  const colors = useColors();
  const [width, setWidth] = React.useState(0);
  const all: ChartSeries[] = series ?? (data ? [{ name: "", values: data.map((d) => d.value) }] : []);
  const names = labels ?? data?.map((d) => d.label) ?? [];
  const say = (v: number) => formatCell(v, format, { currency: CURRENCY, locale: LOCALE });
  const short = (v: number) => (format === "number" ? formatCompact(v, LOCALE) : say(v));

  if (!names.length || !all.length) {
    return <View style={{ height: 80, alignItems: "center", justifyContent: "center" }}><Text tone="muted">No data to chart yet</Text></View>;
  }
  const summary = `${type} chart. ` + names.slice(0, 8).map((n, i) => `${n}: ${say(all[0].values[i] ?? 0)}`).join(", ");
  const max = axisMax(all);
  const legend = all.length > 1 ? (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 8 }}>
      {all.map((s, i) => (
        <View key={s.name || i} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: colors[i % colors.length] }} />
          <Text variant="caption" tone="muted">{s.name}</Text>
        </View>
      ))}
    </View>
  ) : null;

  if (type === "pie" || type === "donut") {
    const values = all[0].values;
    const pct = shares(values);
    return (
      <View accessible accessibilityLabel={summary} style={{ gap: theme.space.md }}>
        <View style={{ flexDirection: "row", height: 16, borderRadius: 8, overflow: "hidden", backgroundColor: theme.colors.muted }}>
          {values.map((v, i) => (pct[i] > 0 ? <View key={i} style={{ flex: pct[i], backgroundColor: colors[i % colors.length] }} /> : null))}
        </View>
        {names.map((n, i) => (
          <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: colors[i % colors.length] }} />
            <Text style={{ flex: 1 }} numberOfLines={1}>{n}</Text>
            <Text tone="muted" style={{ fontVariant: ["tabular-nums"] }}>{say(values[i] ?? 0)}  ·  {pct[i]}%</Text>
          </View>
        ))}
      </View>
    );
  }

  if (type === "line") {
    const plotW = Math.max(0, width - 8);
    return (
      <View accessible accessibilityLabel={summary} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
        <View style={{ height, marginHorizontal: 4, marginTop: 8 }}>
          {width > 0 ? all.map((s, si) => {
            const { points, segments } = linePoints(s.values, max, plotW, height - 8);
            const color = colors[si % colors.length];
            return (
              <React.Fragment key={si}>
                {segments.map((g, i) => (
                  <View key={i} style={{ position: "absolute", left: g.cx - g.length / 2, top: g.cy - 1, width: g.length, height: 2, backgroundColor: color, transform: [{ rotate: `${g.angle}rad` }] }} />
                ))}
                {points.map((p, i) => <View key={i} style={{ position: "absolute", left: p.x - 3, top: p.y - 3, width: 6, height: 6, borderRadius: 3, backgroundColor: color }} />)}
              </React.Fragment>
            );
          }) : null}
        </View>
        <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 4 }}>
          <Text variant="caption" tone="muted" numberOfLines={1}>{names[0]}</Text>
          <Text variant="caption" tone="muted">max {short(max)}</Text>
          <Text variant="caption" tone="muted" numberOfLines={1}>{names[names.length - 1]}</Text>
        </View>
        {legend}
      </View>
    );
  }

  const rows = horizontal ?? (names.length > 6 || names.some((n) => n.length > 9));
  if (rows) {
    return (
      <View accessible accessibilityLabel={summary} style={{ gap: 10 }}>
        {names.map((n, i) => (
          <View key={i} style={{ gap: 3 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 8 }}>
              <Text variant="caption" style={{ flex: 1 }} numberOfLines={1}>{n}</Text>
              <Text variant="caption" tone="muted" style={{ fontVariant: ["tabular-nums"] }}>{say(all[0].values[i] ?? 0)}</Text>
            </View>
            {all.map((s, si) => (
              <View key={si} style={{ height: 10, borderRadius: 5, backgroundColor: theme.colors.muted, overflow: "hidden" }}>
                <View style={{ width: `${Math.round(((s.values[i] ?? 0) > 0 ? (s.values[i] ?? 0) / max : 0) * 100)}%`, height: 10, backgroundColor: colors[si % colors.length] }} />
              </View>
            ))}
          </View>
        ))}
        {legend}
      </View>
    );
  }
  return (
    <View accessible accessibilityLabel={summary}>
      <View style={{ flexDirection: "row", alignItems: "flex-end", height, gap: 8 }}>
        {names.map((n, i) => (
          <View key={i} style={{ flex: 1, alignItems: "center", justifyContent: "flex-end", height }}>
            <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 2 }}>
              {all.map((s, si) => (
                <View key={si} style={{ alignItems: "center", justifyContent: "flex-end" }}>
                  {all.length === 1 ? <Text variant="caption" tone="muted" numberOfLines={1} style={{ fontSize: 10 }}>{short(s.values[i] ?? 0)}</Text> : null}
                  <View style={{ width: all.length === 1 ? 28 : 14, height: barHeight(s.values[i] ?? 0, max, height - 20), borderRadius: 4, backgroundColor: colors[si % colors.length] }} />
                </View>
              ))}
            </View>
          </View>
        ))}
      </View>
      <View style={{ flexDirection: "row", gap: 8, marginTop: 4 }}>
        {names.map((n, i) => <Text key={i} variant="caption" tone="muted" align="center" numberOfLines={1} style={{ flex: 1 }}>{n}</Text>)}
      </View>
      {legend}
    </View>
  );
}
