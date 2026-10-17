/**
 * The parts of the component kit that are decisions, not drawing: a status's
 * tone, a chart's axes and geometry from a widget's rows, the colour tokens, and
 * which screen a person belongs on given their session (signed out -> /login,
 * a public storefront stays open, an organisation to choose -> the picker).
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const ui = await import("../src/ui/logic.ts");
const colors = await import("../src/sdk/colors.ts");
const gate = await import("../src/sdk/gate.ts");

console.log("status tones");
eqJson(["Done", "paid", "in_progress", "Pending", "FAILED", "cancelled", "Open", "mystery", "", null].map((s) => ui.statusTone(s as any)),
  ["success", "success", "info", "warning", "danger", "danger", "info", "neutral", "neutral", "neutral"], "a status is a colour family; an unknown word is neutral, never a guess");
eqJson([ui.initials("Ada Lovelace"), ui.initials("ada"), ui.initials("  "), ui.initials(null), ui.initials("Jean Luc Picard")], ["AL", "A", "?", "?", "JP"], "initials");
eqJson([ui.deltaText(0.12), ui.deltaText(-0.056), ui.deltaText(0), ui.deltaText(null)], [{ text: "▲ 12%", direction: "up" }, { text: "▼ 5.6%", direction: "down" }, { text: "0%", direction: "flat" }, null], "a change against the period before");

console.log("chart data from a widget's rows");
const widget = (dims: any[], measures: any[], extra: object = {}) => ({ id: "W", page: "P", label: "L", kind: "chart", unit: "number", source: { op: "query", entity: "Order", measures, dimensions: dims, filter: {} }, ...extra }) as any;
{
  const w = widget([{ field: "month" }], [{ key: "revenue", aggregation: "sum", label: "Revenue" }, { key: "orders", aggregation: "count" }]);
  const rows = [{ month: "2026-01", revenue: 10, orders: 2 }, { month: "2026-02", revenue: "20", orders: null }];
  eqJson(ui.chartData(w, rows), { labels: ["2026-01", "2026-02"], series: [{ name: "Revenue", values: [10, 20] }, { name: "Orders", values: [2, 0] }] }, "labels along the axis, one series per measure; numbers from text, null as 0");
  eqJson(ui.chartData(widget([{ field: "customerId" }], [{ key: "n", aggregation: "count" }]), [{ customerId: "c1", customerIdLabel: "Acme", n: 3 }]).labels, ["Acme"], "an axis shows a record's NAME (…Label), never its id");
  const split = ui.chartData(widget([{ field: "month" }, { field: "region" }], [{ key: "revenue", aggregation: "sum" }]),
    [{ month: "Jan", region: "EU", revenue: 5 }, { month: "Jan", region: "US", revenue: 7 }, { month: "Feb", region: "EU", revenue: 1 }]);
  eqJson(split, { labels: ["Jan", "Feb"], series: [{ name: "EU", values: [5, 1] }, { name: "US", values: [7, 0] }] }, "a second dimension splits into series, a missing combination is 0");
  eqJson(ui.chartData({ source: { op: "list" } } as any, [{ a: 1 }]), { labels: [], series: [] }, "a list widget has no axes");
  eqJson(ui.chartKind(widget([{ field: "d", bucket: "month" }], [])), "line", "a date-bucketed axis defaults to a line");
  eqJson([ui.chartKind(widget([{ field: "x" }], [])), ui.chartKind(widget([], [], { chart: { mark: "donut" } })), ui.chartKind(widget([], [], { chart: { mark: "area" } })), ui.chartKind(widget([], [], { chart: { mark: "treemap" } }))],
    ["bar", "pie", "line", "bar"], "the widget's own mark, reduced to what can be drawn (the rest are bars)");
  eqJson(ui.shownKeys({ id: "1", customerId: "c1", customerIdLabel: "Acme", total: 5 }), ["customerIdLabel", "total"].length === 2 ? ["customerIdLabel", "total"] : [], "a table row: no id, the name in place of the key");
}

console.log("chart geometry");
eqJson([ui.axisMax([{ name: "a", values: [3, 9] }, { name: "b", values: [4] }]), ui.axisMax([{ name: "a", values: [0, -2] }]), ui.axisMax([])], [9, 1, 1], "the axis reaches the largest value, never 0");
eqJson([ui.barHeight(5, 10, 100), ui.barHeight(0.1, 10, 100), ui.barHeight(0, 10, 100), ui.barHeight(-3, 10, 100), ui.barHeight(5, 0, 100)], [50, 2, 0, 0, 0], "a bar is its share of the axis, a small one still visible, none for zero or less");
{
  const { points, segments } = ui.linePoints([0, 10], 10, 100, 50);
  eqJson(points, [{ x: 0, y: 50 }, { x: 100, y: 0 }], "a line's points in the box, y grows downward");
  ok(segments.length === 1 && Math.abs(segments[0].length - Math.hypot(100, 50)) < 1e-9 && segments[0].cx === 50 && segments[0].cy === 25, "one segment between them, centred");
  eqJson(ui.linePoints([4], 4, 100, 50).segments, [], "a single value is a point, no segment");
  eqJson(ui.linePoints([4], 4, 100, 50).points, [{ x: 50, y: 0 }], "…in the middle");
}
eqJson(ui.shares([1, 1, 2]), [25, 25, 50], "shares of a whole");
eqJson(ui.shares([0, -1, 0]), [0, 0, 0], "nothing to share");
eqJson(ui.shares([3, 0, 1]), [75, 0, 25], "a zero has no share");

console.log("colour tokens");
eqJson(colors.toColor("243 75% 59%"), "#5048e5", "an HSL triplet, as the web projects it, becomes hex");
eqJson([colors.toColor("0 0% 100%"), colors.toColor("0 0% 0%")], ["#ffffff", "#000000"], "white and black");
eqJson(colors.toColor("#123456"), "#123456", "a colour react-native reads is left alone");
const resolved = colors.resolveColors({ primary: "10 50% 50%", bogus: "#fff", accent: "  " });
ok(resolved.primary === colors.toColor("10 50% 50%") && resolved.accent === colors.toColor(colors.DEFAULT_COLORS.accent), "overrides win; a blank one is ignored");
ok(Object.keys(resolved).length === Object.keys(colors.DEFAULT_COLORS).length && !("bogus" in resolved), "every token has a colour; unknown names are ignored");
ok(Object.values(resolved).every((c) => /^#[0-9a-f]{6}$/.test(c)), "every default is a hex react-native can draw");
eqJson([colors.withAlpha("#ff0000", 0.5), colors.withAlpha("red", 0.5)], ["rgba(255,0,0,0.5)", "red"], "alpha on hex; other colours untouched");

console.log("the gate");
const g = (over: object) => gate.gateDecision({ status: "signedOut", needsOrganisation: false, pathname: "/orders", publicRoutes: [], home: "/home", ...over } as any);
eqJson(g({}), "/login", "signed out on a private route: to /login");
eqJson(g({ pathname: "/login" }), null, "signed out on /login: stay");
eqJson(g({ publicRoutes: ["/shop"], pathname: "/shop/item/3" }), null, "a public route's children are public");
eqJson(g({ publicRoutes: ["/shop"], pathname: "/shopping" }), "/login", "…but a route that merely shares its prefix is not");
eqJson([g({ publicRoutes: ["/"], pathname: "/" }), g({ publicRoutes: ["/"], pathname: "/orders" })], [null, "/login"], "'/' public means only the home screen");
eqJson([g({ status: "loading" }), g({ status: "offline" })], [null, null], "nothing is decided until the session is known (offline keeps the person where they are)");
eqJson([g({ status: "signedIn", pathname: "/login" }), g({ status: "signedIn", pathname: "/orders" })], ["/home", null], "signed in leaves /login and is otherwise left alone");
eqJson([g({ status: "signedIn", needsOrganisation: true }), g({ status: "signedIn", needsOrganisation: true, pathname: "/organisation" })], ["/organisation", null], "an organisation to choose: to the picker, and stay");
eqJson(g({ status: "signedIn", pathname: "/organisation" }), "/home", "nothing to choose: the picker leads home");
eqJson(g({ pathname: "/login/" }), null, "a trailing slash is the same route");

done("kit logic and gate");
