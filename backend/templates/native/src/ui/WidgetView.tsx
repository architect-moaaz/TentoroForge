// The component kit — drawing a widget. A widget is an analytic the Blueprint
// attaches to a page: its query (measures by dimensions) and how it is drawn.
// `useWidget(widgets.x)` reads it; this draws what came back, as the web's
// `<WidgetView />` does, and the encoding follows from the query's own shape —
// a chart cannot be drawn against columns its data does not have:
//
//   const sales = useWidget(widgets.salesByMonth);
//   <WidgetView widget={widgets.salesByMonth} data={sales.data} />
//
//   metric   a StatTile: the number, with its change over the period before
//   gauge    a meter against a round maximum (percent units read as 0-100)
//   text     the number, large
//   chart    bar / line / pie as the widget says, with a table of the numbers behind it
//   list, table, feed   the rows, as a list
//
// Props: `title={false}` when the screen already heads this widget; `action` is
// something in the card's header ("View all"); `currency` overrides the app's.

import * as React from "react";
import { View } from "react-native";
import { useTheme } from "../theme";
import { Text } from "./Text";
import { Card } from "./Layout";
import { Button } from "./Button";
import { StatTile } from "./Display";
import { SimpleChart } from "./SimpleChart";
import { CURRENCY } from "../sdk/money";
import { LOCALE } from "../config.generated";
import { formatCell, humanize, niceCeiling, type Format } from "../sdk/format";
import type { WidgetData } from "../sdk/reads";
import type { WidgetRef } from "../sdk/widgets";
import { chartData, chartKind, shownKeys } from "./logic";

export interface WidgetViewProps {
  widget: WidgetRef;
  /** What `useWidget(widget)` returned. */
  data: WidgetData | null | undefined;
  /** Chart height in points (default 200). */
  height?: number;
  /** ISO 4217 code for a currency widget (default: the app's). */
  currency?: string;
  /** Something for the card's header — a "View all" button. */
  action?: React.ReactNode;
  /** The card draws the widget's own title and description. Pass `false` when
   *  the screen already heads this widget. */
  title?: boolean;
}

function formatOf(unit: WidgetRef["unit"]): Format {
  return unit === "currency" || unit === "percent" || unit === "duration" ? unit : "number";
}

function Rows({ rows, format, currency }: { rows: NonNullable<WidgetData["rows"]>; format: Format; currency: string }) {
  const theme = useTheme();
  if (!rows.length) return <Text tone="muted" align="center" style={{ paddingVertical: theme.space.xl }}>No data for this period yet</Text>;
  const keys = shownKeys(rows[0]);
  const cell = (v: unknown) => formatCell(v, format, { currency, locale: LOCALE });
  return (
    <View style={{ gap: theme.space.sm }}>
      {rows.slice(0, 50).map((r, i) => (
        <View key={i} style={{ gap: 2, paddingVertical: theme.space.xs, borderBottomWidth: i < rows.length - 1 ? 1 : 0, borderBottomColor: theme.colors.border }}>
          <Text variant="label" numberOfLines={1}>{cell(r[keys[0]])}</Text>
          {keys.length > 1 ? (
            <Text variant="caption" tone="muted" numberOfLines={2}>
              {keys.slice(1, 5).map((k) => `${humanize(k)} ${cell(r[k])}`).join("  ·  ")}
            </Text>
          ) : null}
        </View>
      ))}
    </View>
  );
}

export function WidgetView({ widget, data, height = 200, currency = CURRENCY, action, title = true }: WidgetViewProps) {
  const theme = useTheme();
  const [asTable, setAsTable] = React.useState(false);
  const rows = data?.rows ?? [];
  const format = formatOf(widget.unit);
  const say = (v: unknown) => formatCell(v, format, { currency, locale: LOCALE });

  if (widget.kind === "metric") {
    return <StatTile label={widget.label} value={data?.value == null ? null : say(data.value)} delta={data?.delta} hint={title ? widget.description : undefined} />;
  }

  let body: React.ReactNode;
  let toggle = false;
  if (widget.kind === "gauge") {
    const v = data?.value ?? 0;
    const percent = format === "percent";
    const shown = percent ? v * 100 : v;
    const max = percent ? 100 : niceCeiling(v);
    body = (
      <View accessible accessibilityRole="progressbar" accessibilityLabel={`${widget.label}: ${say(v)}`} accessibilityValue={{ min: 0, max, now: Math.min(shown, max) }} style={{ gap: theme.space.sm }}>
        <Text variant="display" style={{ fontSize: 28, lineHeight: 34 }}>{say(v)}</Text>
        <View style={{ height: 12, borderRadius: 6, backgroundColor: theme.colors.muted, overflow: "hidden" }}>
          <View style={{ width: `${Math.max(0, Math.min(100, (shown / max) * 100))}%`, height: 12, backgroundColor: theme.colors.primary }} />
        </View>
      </View>
    );
  } else if (widget.kind === "text") {
    body = <Text variant="display" style={{ fontSize: 28, lineHeight: 34 }}>{say(data?.value ?? rows[0]?.[Object.keys(rows[0] ?? {})[0]])}</Text>;
  } else if (widget.kind === "chart" && widget.source.op === "query") {
    toggle = rows.length > 0;
    const chart = chartData(widget, rows);
    body = asTable
      ? <Rows rows={rows} format={format} currency={currency} />
      : <SimpleChart type={chartKind(widget)} labels={chart.labels} series={chart.series} format={format} height={height} horizontal={widget.chart?.horizontal} />;
  } else {
    body = <Rows rows={rows} format={format} currency={currency} />;
  }

  return (
    <Card>
      <View style={{ gap: theme.space.md }}>
        <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: theme.space.sm }}>
          <View style={{ flex: 1, gap: 2 }}>
            {title ? <Text variant="label">{widget.label}</Text> : null}
            {title && widget.description ? <Text variant="caption" tone="muted">{widget.description}</Text> : null}
          </View>
          {action}
          {toggle ? <Button variant="ghost" size="sm" onPress={() => setAsTable((t) => !t)} accessibilityLabel={asTable ? "Show chart" : "Show as table"}>{asTable ? "Chart" : "Table"}</Button> : null}
        </View>
        {body}
      </View>
    </Card>
  );
}
