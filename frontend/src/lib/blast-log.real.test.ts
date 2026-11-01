/**
 * A REAL blast stream, captured from the platform while it threw four bombs at ResolveDesk's agent with the real model
 * (src/lib/__fixtures__/blast-real-stream.json), replayed through the log logic.
 *
 * The other tests use events written by hand. This one pins that what the platform REALLY streams reads well as a
 * terminal: every bomb is announced, its steps carry its tag, every bomb ends with a verdict, the log closes with the
 * totals, and nothing prints as "undefined".
 */
import { describe, it, expect } from "vitest";
import fixture from "./__fixtures__/blast-real-stream.json";
import { appendLines, linesForEvent, stamp, type LogLine } from "./blast-log";

const events = fixture.events as any[];
const bombs = fixture.bombs as Record<string, string>;
const start = events.find((e) => e.type === "start");
const ctx = { total: start.total, bombTitle: (k?: string | null) => (k ? bombs[k] ?? null : null) };

const replay = (): LogLine[] => {
  let log: LogLine[] = [];
  let id = 1;
  events.forEach((e, i) => ({ log, nextId: id } = appendLines(log, linesForEvent(e, ctx), i * 1000, id)));
  return log;
};

describe("a real blast stream, replayed", () => {
  it("announces every bomb, and ends every bomb with a verdict", () => {
    const log = replay();
    const starts = log.filter((l) => l.kind === "cmd");
    const verdicts = log.filter((l) => /DEFUSED|EXPLODED|UNSTABLE|MISFIRE/.test(l.text));
    expect(starts).toHaveLength(start.total);
    expect(verdicts).toHaveLength(start.total);
  });

  it("tags each step with its bomb's number, so interleaved lines can be told apart", () => {
    const steps = events.filter((e) => e.type === "step");
    expect(steps.length).toBeGreaterThan(start.total);
    for (const e of steps) {
      const lines = linesForEvent(e, ctx);
      for (const l of lines) expect(l.text.startsWith(`[${e.index}]`), l.text).toBe(true);
    }
  });

  it("shows the story of each bomb: the tool it asked for, what came back, and what it said", () => {
    const text = replay().map((l) => l.text).join("\n");
    expect(text).toMatch(/› asks to use \w+ \((lookup|change|hand-over)\)/);
    expect(text).toMatch(/← \w+: (\d+ records?|no records|returned data|error: .+)/);
    expect(text).toMatch(/✎ replies \(\d+ characters\)/);
  });

  it("closes with the totals as the platform counted them", () => {
    const log = replay();
    const last = log.at(-1)!;
    expect(last.text.startsWith("Done. ")).toBe(true);
    const summary = events.find((e) => e.type === "done").summary;
    expect(summary.total).toBe(start.total);
    expect(last.kind).toBe(summary.failed + summary.flaky > 0 ? "bad" : summary.error ? "warn" : "good");
  });

  it("never prints a hole where something was missing", () => {
    for (const l of replay()) {
      expect(l.text).not.toMatch(/undefined|null|NaN|\[object/);
      expect(l.text.length).toBeLessThan(220);
    }
  });

  it("is readable: here is the terminal for this run", () => {
    const log = replay();
    // eslint-disable-next-line no-console
    console.log("\n" + log.map((l) => `${stamp(l.t)} ${l.text}`).join("\n") + "\n");
    expect(log.length).toBeGreaterThan(start.total * 3);
  });
});
