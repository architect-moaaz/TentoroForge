/**
 * A `wait` of two days puts the run down (a wait_timer task with its due
 * time) instead of sleeping; one of a second sleeps in place. `"1 hour"`
 * used to be `Number("1 hour")`, NaN: no wait ever waited.
 *
 * Runs the SHIPPED engine.ts.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({ stubs: {
  "../feel-lite": "export const evaluateExpression = () => true;",
  "./types": "export default {};",
} });

const engine: any = await import("../workflows/engine.ts");

const def = (waitConfig: Record<string, unknown>) => ({ id: "follow-up", name: "Follow up", definition: {
  trigger: { type: "manual" },
  nodes: [
    { id: "trigger", type: "trigger", data: { label: "Start", config: {} } },
    { id: "pause", type: "wait", data: { label: "Give them time", config: waitConfig } },
    { id: "end", type: "end", data: { label: "Done", config: {} } },
  ],
  edges: [{ id: "e1", source: "trigger", target: "pause" }, { id: "e2", source: "pause", target: "end" }],
} });

{
  const result = await engine.executeWorkflow(def({ for: "2 days" }), {}, { id: "u-1" });
  eqJson(result.status, "paused", "a two-day wait pauses the run");
  eqJson(result.pendingTask?.taskType, "wait_timer", "as a timer task the clock ends");
  eqJson(result.pendingTask?.dueIn, 2880, "due in two days of minutes");
  eqJson(result.output.__waiting_event, "__timer", "marked for the bus like an awaited event");
}
{
  const t0 = Date.now();
  const result = await engine.executeWorkflow(def({ for: "1 second" }), {}, { id: "u-1" });
  eqJson(result.status, "completed", "a one-second wait is held in place");
  ok(Date.now() - t0 >= 900, "and actually waited");
}
{
  const result = await engine.executeWorkflow(def({ duration: "1 hour" }), {}, { id: "u-1" });
  eqJson(result.status, "paused", "the old words are read as words, not as NaN");
  eqJson(result.pendingTask?.dueIn, 60, "an hour");
}
eqJson(engine.parseDurationMs("PT90M"), 5_400_000, "ISO-8601 is read");
eqJson(engine.parseDurationMs("1 hour 30 minutes"), 5_400_000, "words are read");
eqJson(engine.parseDurationMs("soon"), 0, "nonsense is zero, for the author's check to refuse");
done("a wait is a pause, not a sleep");
