/**
 * The Insights charts (components/agent-builder/insights-charts.tsx): the drawing rules and the hover layer.
 *
 * Pinned: marks take their colour from the validated tokens and never from a raw colour; text is never in a series colour; red is used
 * only for failures; a failed part is the top of its column, after a gap; one measure per chart; a line breaks where a price is unknown
 * instead of dropping to zero; the pointer and the keyboard show the SAME one tooltip with the value first and the name second; the
 * legend shows only when there is more than one series; and each small figure (meter, speed range, token split, tool bars) says its
 * numbers in words as well as in the drawing.
 */
import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { ColumnChart, LineChart, Meter, RoleBars, roleWords, ShareBar, Sparkline, SpeedRange, TokenSplit, ToolBars, VIZ_CSS, type DayDatum } from "../insights-charts";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const DAYS: DayDatum[] = [
  { day: "2026-10-19", turns: 4, errors: 0, usd: 0.1 },
  { day: "2026-10-20", turns: 10, errors: 0, usd: 0.5 },
  { day: "2026-10-21", turns: 30, errors: 2, usd: 2.03 },
];

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const mount = (node: React.ReactElement) => act(async () => { root.render(node); });
const q = (sel: string) => container.querySelector(sel) as HTMLElement | null;
const qa = (sel: string) => [...container.querySelectorAll(sel)] as HTMLElement[];
const fire = (el: Element, type: string, init: Record<string, unknown> = {}) =>
  act(async () => { el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, ...init })); });
const key = (el: Element, k: string) => act(async () => { el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); });
const focus = (el: Element) => act(async () => { el.dispatchEvent(new FocusEvent("focusin", { bubbles: true })); });
const tip = () => q('[data-testid="insights-tooltip"]');
const fillOf = (el: Element) => (el as HTMLElement).style.fill;

describe("the colour rules", () => {
  it("every mark takes its colour from a token, never from a raw colour", async () => {
    await mount(<div className="viz"><ColumnChart days={DAYS} /><LineChart days={DAYS} /><Sparkline values={[1, 2, 3]} wide /><TokenSplit inputTokens={900} outputTokens={100} /><Meter pct={40} label="x" /></div>);
    const html = container.innerHTML;
    expect(html.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [], "a colour written into a mark would not follow the theme").toEqual([]);
    expect(VIZ_CSS).toContain("--viz-s1: #2a78d6");
    expect(VIZ_CSS, "the dark values are there for when the app has a dark theme").toContain('[data-theme="dark"]');
  });

  it("never colours text in a series colour: only marks beside it carry the colour", async () => {
    await mount(<div className="viz"><ColumnChart days={DAYS} /><LineChart days={DAYS} /><TokenSplit inputTokens={900} outputTokens={100} /></div>);
    for (const t of qa("text")) expect(fillOf(t), t.textContent ?? "").toMatch(/viz-(ink|ink-2|muted)/);
    for (const el of qa("[data-testid=insights-token-split] span.font-semibold")) expect(el.style.color).toContain("viz-ink");
  });
});

describe("replies each day: columns", () => {
  it("draws one group a day, the failed part on top in red, and says each day in words", async () => {
    await mount(<ColumnChart days={DAYS} />);
    const bars = qa('[data-testid="insights-bar"]');
    expect(bars.map((b) => b.getAttribute("aria-label"))).toEqual(["Oct 19: 4 replies", "Oct 20: 10 replies", "Oct 21: 30 replies, 2 failed"]);
    const paths = (b: Element) => [...b.querySelectorAll("path")];
    expect(paths(bars[0])).toHaveLength(1);
    expect(fillOf(paths(bars[0])[0])).toContain("--viz-s1");
    const [ok, bad] = paths(bars[2]);
    expect([fillOf(ok), fillOf(bad)]).toEqual(["var(--viz-s1)", "var(--viz-bad)"]);
    // the failed part is above the good part, with a gap between them (smaller y is higher)
    const top = (p: Element) => Number(p.getAttribute("d")!.match(/Q[\d.]+ ([\d.]+)/)?.[1] ?? p.getAttribute("d")!.match(/L[\d.]+ ([\d.]+)/)![1]);
    expect(top(bad)).toBeLessThan(top(ok));
  });

  it("labels only the busiest day, and shows no legend box when there is only one series", async () => {
    const noFailures = DAYS.map((d) => ({ ...d, errors: 0 }));
    await mount(<ColumnChart days={noFailures} />);
    expect(q('[data-testid="insights-peak-label"]')!.textContent).toBe("30");
    expect(qa("text").filter((t) => t.getAttribute("font-weight") === "600")).toHaveLength(1);
    expect(q('[data-testid="insights-column-legend"]'), "one colour: the title already says what it is").toBeNull();
    await mount(<ColumnChart days={DAYS} />);
    expect(q('[data-testid="insights-column-legend"]')!.textContent).toContain("Replies that failed");
  });

  it("has a zero-based axis with whole-number ticks and a baseline", async () => {
    await mount(<ColumnChart days={DAYS} />);
    const ticks = qa("svg text").map((t) => t.textContent).filter((t) => /^\d+$/.test(t ?? ""));
    expect(ticks[0]).toBe("0");
    expect(ticks.every((t) => Number.isInteger(Number(t)))).toBe(true);
    expect(Math.max(...ticks.map(Number))).toBeGreaterThanOrEqual(30);
    expect(qa("svg line").every((l) => !l.getAttribute("stroke-dasharray")), "solid hairlines, never dashed").toBe(true);
  });

  it("shows ONE tooltip for the day under the pointer, value first and name second", async () => {
    await mount(<ColumnChart days={DAYS} />);
    expect(tip()).toBeNull();
    const hits = qa('[data-testid="insights-bar"] rect');
    await fire(hits[2], "pointerover");
    expect(qa('[data-testid="insights-tooltip"]')).toHaveLength(1);
    const rows = [...tip()!.querySelectorAll("div.mt-1")].map((r) => [r.children[1].textContent, r.children[2].textContent]);
    expect(rows).toEqual([["30", "replies"], ["2", "failed"]]);
    expect(tip()!.textContent).toContain("Oct 21");
    await fire(hits[0], "pointermove");
    expect(tip()!.textContent).toContain("Oct 19");
    expect(qa('[data-testid="insights-tooltip"]')).toHaveLength(1);
  });

  it("shows the same tooltip from the keyboard: one tab stop, arrows, Home, End and Escape", async () => {
    await mount(<ColumnChart days={DAYS} />);
    const chart = q('svg[role="group"]')!;
    expect(chart.getAttribute("tabindex")).toBe("0");
    expect(qa("[tabindex]").filter((e) => e !== chart), "a long chart is not a long run of tab stops").toHaveLength(0);
    await focus(chart);
    expect(tip()!.textContent, "focus starts on the latest day").toContain("Oct 21");
    await key(chart, "ArrowLeft");
    expect(tip()!.textContent).toContain("Oct 20");
    await key(chart, "Home");
    expect(tip()!.textContent).toContain("Oct 19");
    await key(chart, "ArrowLeft");
    expect(tip()!.textContent, "stops at the first day").toContain("Oct 19");
    await key(chart, "End");
    expect(tip()!.textContent).toContain("Oct 21");
    await key(chart, "Escape");
    expect(tip()).toBeNull();
  });

  it("copes with no days and with a day of nothing", async () => {
    await mount(<ColumnChart days={[]} />);
    expect(q("svg")).toBeTruthy();
    await mount(<ColumnChart days={[{ day: "2026-10-21", turns: 0, errors: 0, usd: null }]} />);
    expect(q('[data-testid="insights-peak-label"]')).toBeNull();
    expect(qa("path")).toHaveLength(0);
  });
});

describe("estimated cost each day: line", () => {
  it("is one 2px line over a faint wash, with an end dot that has a ring, and the latest value", async () => {
    await mount(<LineChart days={DAYS} />);
    const line = q('[data-testid="insights-line"]')!;
    expect(line.getAttribute("stroke-width")).toBe("2");
    expect(line.getAttribute("stroke-linecap")).toBe("round");
    expect(fillOf(line)).toBe("");
    expect(qa("path").some((p) => p.getAttribute("opacity") === "0.1"), "the area is a wash, not a block").toBe(true);
    const dots = qa("circle");
    expect(dots.map((d) => d.getAttribute("r"))).toEqual(["6", "4"]);
    expect(fillOf(dots[0])).toContain("--viz-surface");
    expect(fillOf(dots[1])).toContain("--viz-s1");
    expect(q('[data-testid="insights-end-label"]')!.textContent).toBe("$2.03");
  });

  it("puts the latest value where the line is not: under the dot when the line comes down into it, above when it climbs", async () => {
    const dotY = () => Number(qa("circle")[1].getAttribute("cy"));
    const labelY = () => Number(q('[data-testid="insights-end-label"]')!.getAttribute("y"));
    await mount(<LineChart days={[{ ...DAYS[0], usd: 0.5 }, { ...DAYS[1], usd: 2 }, { ...DAYS[2], usd: 1.2 }]} />);
    expect(labelY(), "falling into the last day: label under the dot").toBeGreaterThan(dotY());
    await mount(<LineChart days={[{ ...DAYS[0], usd: 0.5 }, { ...DAYS[1], usd: 1 }, { ...DAYS[2], usd: 2 }]} />);
    expect(labelY(), "climbing into the last day: label above the dot").toBeLessThan(dotY());
  });

  it("breaks where a price is unknown instead of dropping to zero, and says so in the tooltip", async () => {
    const gap = [DAYS[0], { ...DAYS[1], usd: null }, DAYS[2]];
    await mount(<LineChart days={gap} />);
    expect(qa('[data-testid="insights-line"]'), "two separate runs, nothing joins them").toHaveLength(2);
    await fire(qa('[data-testid="insights-day-hit"]')[1], "pointerover");
    expect(tip()!.textContent).toContain("price unknown");
    expect(tip()!.textContent).not.toContain("$0");
    expect(q('[data-testid="insights-end-label"]'), "while hovering, the end label gets out of the way").toBeNull();
  });

  it("snaps a crosshair and a ringed dot to the day under the pointer, with its cost first", async () => {
    await mount(<LineChart days={DAYS} />);
    expect(qa("line").filter((l) => l.getAttribute("aria-hidden") === "true")).toHaveLength(0);
    await fire(qa('[data-testid="insights-day-hit"]')[1], "pointerover");
    expect(qa("line").filter((l) => l.getAttribute("aria-hidden") === "true"), "the crosshair").toHaveLength(1);
    expect(qa("circle")).toHaveLength(2);
    const row = tip()!.querySelector("div.mt-1")!;
    expect([row.children[1].textContent, row.children[2].textContent]).toEqual(["$0.50", "estimated cost"]);
    expect(tip()!.textContent).toContain("10 replies");
    await key(q('svg[role="group"]')!, "Escape");
  });

  it("has a dollar axis from zero", async () => {
    await mount(<LineChart days={DAYS} />);
    const ticks = qa("svg text").map((t) => t.textContent).filter((t) => /^\$/.test(t ?? "") && t !== "$2.03");
    expect(ticks[0]).toBe("$0");
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });
});

describe("the small figures", () => {
  it("a sparkline is grey with the latest day in the accent, and flat when there is nothing", async () => {
    await mount(<Sparkline values={[1, 3, 2]} />);
    expect(fillOf(qa("circle")[1])).toContain("--viz-s1");
    expect(qa("path")[0].style.stroke).toContain("--viz-quiet");
    expect(q('[data-testid="insights-sparkline"]')!.getAttribute("aria-hidden"), "decorative: the number beside it says it").toBe("true");
    await mount(<Sparkline values={[null, null]} />);
    expect(qa("circle")).toHaveLength(0);
    expect(qa("line")).toHaveLength(1);
  });

  it("a meter says its value to a screen reader, clamps, and turns red only when told it is bad", async () => {
    await mount(<Meter pct={40} label="Thumbs up" />);
    const m = q('[role="meter"]')!;
    expect([m.getAttribute("aria-valuenow"), m.getAttribute("aria-label")]).toEqual(["40", "Thumbs up"]);
    expect((m.firstElementChild as HTMLElement).style.background).toContain("--viz-s1");
    await mount(<Meter pct={250} bad label="x" />);
    expect(q('[role="meter"]')!.getAttribute("aria-valuenow")).toBe("100");
    expect((q('[role="meter"]')!.firstElementChild as HTMLElement).style.background).toContain("--viz-bad");
    await mount(<Meter pct={null} label="x" />);
    expect(q('[role="meter"]')).toBeNull();
    await mount(<Meter pct={0} label="x" />);
    expect((q('[role="meter"]')!.firstElementChild as HTMLElement).style.width).toBe("0%");
  });

  it("the speed range names the typical reply, the slowest 1 in 20 and the limit, and flags the limit only when it is passed", async () => {
    await mount(<SpeedRange p50Ms={7100} p95Ms={13000} />);
    const range = q('[data-testid="insights-speed-range"]')!;
    expect(range.textContent).toContain("Typical 7.1 s");
    expect(range.textContent).toContain("Slowest 1 in 20: 13 s");
    expect(range.textContent, "the limit is named on the drawing itself").toContain("30 s");
    expect(range.querySelector("svg")!.getAttribute("aria-label")).toBe("Typical 7.1 s, slowest 1 in 20 13 s, limit 30 s");
    const limit = (r: Element) => [...r.querySelectorAll("svg line")][0] as SVGElement;
    expect(limit(range).style.stroke).toContain("--viz-axis");
    await mount(<SpeedRange p50Ms={9000} p95Ms={41000} />);
    expect(limit(q('[data-testid="insights-speed-range"]')!).style.stroke, "over 30 s: the line turns red").toContain("--viz-bad");
  });

  it("the token split is two shares with a gap, named underneath, and a tiny share is still seen and named", async () => {
    await mount(<TokenSplit inputTokens={113_322} outputTokens={1_420} />);
    const split = q('[data-testid="insights-token-split"]')!;
    const parts = [...split.querySelector('[role="img"]')!.children] as HTMLElement[];
    expect(parts).toHaveLength(2);
    expect(parts[0].style.background).toContain("--viz-s1");
    expect(parts[1].style.background).toContain("--viz-s2");
    expect(parseFloat(parts[1].style.width)).toBeGreaterThanOrEqual(3);
    expect(split.textContent).toContain("Read by the assistant");
    expect(split.textContent).toContain("113.3k");
    expect(split.textContent).toContain("98.8%");
    expect(split.textContent).toContain("1.2%");
    await mount(<TokenSplit inputTokens={0} outputTokens={50} />);
    expect([...q('[data-testid="insights-token-split"] [role="img"]')!.children], "one share fills the bar").toHaveLength(1);
  });

  it("the tool bars leave room for the number at the tip of the longest bar, so it never runs into the words beside it", async () => {
    await mount(<ToolBars tools={[{ name: "list_pets", calls: 61, errors: 0, avgMs: 5900 }, { name: "list_veterinarians", calls: 9, errors: 0, avgMs: 124 }]} />);
    const rows = qa('[data-testid="insights-tool-bar"]');
    const cells = (r: Element) => [...r.children] as HTMLElement[];
    for (const r of rows) {
      const [name, barCell, tail] = cells(r);
      const bar = (barCell.firstElementChild as HTMLElement);
      const number = barCell.lastElementChild as HTMLElement;
      const barW = [...bar.children].reduce((sum, b) => sum + parseFloat((b as HTMLElement).style.width || "0"), 0);
      expect(barW + 8 + 28, "the bar and its number fit in their own cell").toBeLessThanOrEqual(parseFloat(barCell.style.width));
      expect(number.textContent).toMatch(/^\d+$/);
      expect([name, barCell, tail].every((c) => c.className.includes("shrink-0")), "no column shrinks, so every row lines up").toBe(true);
    }
    expect(parseFloat(cells(rows[0])[1].style.width)).toBe(parseFloat(cells(rows[1])[1].style.width));
  });

  it("the tool bars are busiest first, end in red for the failed part, and say it in words", async () => {
    await mount(<ToolBars tools={[
      { name: "issue_refund", calls: 10, errors: 8, avgMs: 2500 },
      { name: "lookup_order", calls: 40, errors: 0, avgMs: 120 },
    ]} />);
    const rows = qa('[data-testid="insights-tool-bar"]');
    expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual(["issue_refund: 10 calls, 8 failed, about 2.5 s each", "lookup_order: 40 calls, about 120 ms each"]);
    expect(rows[0].textContent).toContain("8 failed");
    expect(rows[1].textContent).toContain("120 ms each");
    const bars = (r: Element) => ([...r.querySelectorAll("span.h-3")] as HTMLElement[]).filter((b) => b.style.background !== "");
    expect(bars(rows[0]).map((b) => b.style.background)).toEqual(["var(--viz-s1)", "var(--viz-bad)"]);
    expect(bars(rows[1]).map((b) => b.style.background), "nothing failed: one blue bar").toEqual(["var(--viz-s1)"]);
    expect(parseFloat(bars(rows[1])[0].style.width), "40 calls is a longer bar than 10").toBeGreaterThan(parseFloat(bars(rows[0])[0].style.width) + parseFloat(bars(rows[0])[1].style.width) - 1);
  });
});

describe("columns and lines for an hour, a minute or people", () => {
  const HOURS: DayDatum[] = Array.from({ length: 24 }, (_, i) => ({
    day: `2026-10-21T${String(i).padStart(2, "0")}:00:00Z`, label: `Oct 21, ${String(i).padStart(2, "0")}:00`, turns: (i % 5) + 1, errors: 0, usd: 0.01 * (i + 1),
  }));

  it("names each column by its own label (or a longer title for a column that covers several), not by a day", async () => {
    const grouped: DayDatum[] = [{ day: "a", label: "10:00", title: "10:00 to 10:11", turns: 12, errors: 1, usd: null }, { day: "b", label: "10:12", turns: 3, errors: 0, usd: null }];
    await mount(<ColumnChart days={grouped} what="Replies each minute" />);
    expect(qa('[data-testid="insights-bar"]').map((b) => b.getAttribute("aria-label"))).toEqual(["10:00 to 10:11: 12 replies, 1 failed", "10:12: 3 replies"]);
    expect(q("svg")!.getAttribute("aria-label")).toBe("Replies each minute, from 10:00 to 10:12. Use the arrow keys to move along the columns.");
  });

  it("says people, not replies, when told what it counts, and the tooltip follows", async () => {
    const people: DayDatum[] = [{ day: "2026-10-20", turns: 1, errors: 0, usd: null }, { day: "2026-10-21", turns: 41000, errors: 0, usd: null }];
    await mount(<ColumnChart days={people} what="People active each day" noun={["person", "people"]} />);
    expect(qa('[data-testid="insights-bar"]').map((b) => b.getAttribute("aria-label"))).toEqual(["Oct 20: 1 person", "Oct 21: 41000 people"]);
    await focus(q("svg")!);
    expect(tip()!.textContent).toContain("41000");
    expect(tip()!.textContent).toContain("people");
    expect(tip()!.textContent).not.toContain("repl");
  });

  it("keeps wide axis labels apart, by what each covers, and keeps the newest", async () => {
    await mount(<ColumnChart days={HOURS} />);
    const labels = qa("svg text").filter((t) => /^Oct 21, \d\d:00$/.test(t.textContent ?? ""));
    expect(labels.length).toBeGreaterThan(1);
    const spans = labels.map((t) => {
      const x = Number(t.getAttribute("x"));
      const w = (t.textContent ?? "").length * 5.6;
      const a = t.getAttribute("text-anchor");
      const left = a === "end" ? x - w : a === "start" ? x : x - w / 2;
      return [left, left + w];
    }).sort((p, r) => p[0] - r[0]);
    for (let i = 1; i < spans.length; i++) expect(spans[i][0] - spans[i - 1][1]).toBeGreaterThanOrEqual(8);
    expect(labels.some((t) => t.textContent === "Oct 21, 23:00")).toBe(true);
  });

  it("the line draws and names hours the same way, and its tooltip title is the label", async () => {
    await mount(<LineChart days={HOURS} what="Estimated cost each hour" />);
    expect(q("svg")!.getAttribute("aria-label")).toContain("Estimated cost each hour, from Oct 21, 00:00 to Oct 21, 23:00");
    await focus(q("svg")!);
    expect(tip()!.querySelector("div")!.textContent).toBe("Oct 21, 23:00");
  });

  it("two columns with the same start (a repeated day) do not collide", async () => {
    const twin: DayDatum[] = [{ day: "x", turns: 1, errors: 0, usd: null }, { day: "x", turns: 2, errors: 0, usd: null }];
    await mount(<ColumnChart days={twin} />);
    expect(qa('[data-testid="insights-bar"]')).toHaveLength(2);
  });
});

describe("who is using it: one bar of shares and the role bars", () => {
  it("the share bar is one bar with a 2px gap between parts, each part named with its number and share, in series colours only on marks", async () => {
    await mount(<div className="viz"><ShareBar label="New and returning people" parts={[{ name: "New", value: 12000, tone: "s1" }, { name: "Returning", value: 38000, tone: "s2" }]} /></div>);
    const bar = q('[role="img"]')!;
    expect(bar.className).toContain("gap-0.5");
    expect(bar.children).toHaveLength(2);
    expect((bar.children[0] as HTMLElement).style.background).toBe("var(--viz-s1)");
    expect((bar.children[1] as HTMLElement).style.background).toBe("var(--viz-s2)");
    const widths = [...bar.children].map((c) => parseFloat((c as HTMLElement).style.width));
    expect(widths[0] + widths[1] + 2, "the two parts and the gap fill the bar").toBeCloseTo(480, 0);
    expect(widths[1] / widths[0]).toBeCloseTo(38 / 12, 1);
    expect(q("[data-testid=insights-share-bar]")!.textContent).toBe("New12,00024%Returning38,00076%");
    for (const el of qa("[data-testid=insights-share-bar] span.font-semibold")) expect(el.style.color).toContain("viz-ink");
    expect(container.innerHTML.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).toEqual([]);
  });

  it("a very thin part is still drawn and named, and an empty whole is an empty track", async () => {
    await mount(<ShareBar label="x" parts={[{ name: "New", value: 1, tone: "s1" }, { name: "Returning", value: 100000, tone: "s2" }]} />);
    const bar = q('[role="img"]')!;
    expect(parseFloat((bar.children[0] as HTMLElement).style.width)).toBeGreaterThanOrEqual(3);
    expect(q("[data-testid=insights-share-bar]")!.textContent).toContain("0%");
    await mount(<ShareBar label="x" parts={[{ name: "New", value: 0, tone: "s1" }, { name: "Returning", value: 0, tone: "s2" }]} />);
    expect(q('[role="img"]')!.children).toHaveLength(1);
    expect(q("[data-testid=insights-share-bar]")!.textContent).toContain("0%");
  });

  it("says about before the people counts when they are approximate", async () => {
    await mount(<ShareBar approximate label="x" parts={[{ name: "New", value: 10, tone: "s1" }, { name: "Returning", value: 30, tone: "s2" }]} />);
    expect(q('[role="img"]')!.getAttribute("aria-label")).toBe("x: New about 10 (25%), Returning about 30 (75%)");
  });

  it("role bars: one measure on the bar, the rest in words under the role, longest bar for the busiest", async () => {
    const roles = [{ role: "Admin", users: 3, turns: 1200, usd: 4.5, thumbsDownPct: 3.24 }, { role: "Agent", users: 1, turns: 300, usd: null, thumbsDownPct: null }];
    await mount(<div className="viz"><RoleBars roles={roles} /></div>);
    const bars = qa('[data-testid="insights-role-bar"]');
    expect(bars.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Admin: 1,200 replies, 3 people, estimated cost $4.50, 3.2% thumbs down",
      "Agent: 300 replies, 1 person, estimated cost n/a (price unknown), no ratings yet",
    ]);
    expect(roleWords(roles[1], false)).toBe("1 person, estimated cost n/a (price unknown), no ratings yet");
    const w = (b: HTMLElement) => b.querySelector<HTMLElement>("span.h-3")!.style.width;
    expect(w(bars[0])).toBe("calc(100% - 64px)");
    expect(w(bars[1])).toBe("calc(25% - 64px)");
    expect(bars[0].querySelector<HTMLElement>("span.h-3")!.style.background).toBe("var(--viz-s1)");
    for (const el of bars[0].querySelectorAll("span.font-semibold, span.truncate")) expect((el as HTMLElement).style.color).toContain("viz-ink");
    expect(container.innerHTML.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).toEqual([]);
  });

  it("role bars with approximate people say about", async () => {
    await mount(<RoleBars approximate roles={[{ role: "Admin", users: 3000, turns: 5, usd: 1, thumbsDownPct: 12 }]} />);
    expect(q('[data-testid="insights-role-bar"]')!.getAttribute("aria-label")).toBe("Admin: 5 replies, about 3,000 people, estimated cost $1.00, 12% thumbs down");
  });

  it("hovering a role bar lights its row", async () => {
    await mount(<RoleBars roles={[{ role: "Admin", users: 1, turns: 5, usd: 1, thumbsDownPct: null }]} />);
    const row = q('[data-testid="insights-role-bar"]')!;
    await fire(row, "pointerover");
    expect(row.getAttribute("style") ?? "").toContain("viz-grid");
  });
});
