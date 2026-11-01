/**
 * What an agent "is" for the builder, as text: it must change when the agent changes and not when a box is only moved,
 * and it must be cheap, because the page works it out on every render and a real agent has dozens of boxes with
 * kilobytes of prompts. What is pinned: the same text for the same agent whatever the positions, a different text for
 * every real change, and that a box that did not change is NOT turned into text again.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { checkKeyOf, dataText, draftKeyOf } from "./agent-draft";
import type { AgentEdgeSerialized, AgentNodeSerialized } from "@/types/agent-builder";

const node = (id: string, data: Record<string, unknown>, x = 0, y = 0) =>
  ({ id, type: "tool", position: { x, y }, data: { label: id, nodeType: "tool", config: {}, ...data } }) as unknown as AgentNodeSerialized;
const edge = (source: string, target: string) => ({ id: `${source}-${target}`, source, target }) as AgentEdgeSerialized;

afterEach(() => vi.restoreAllMocks());

describe("what an agent is, as text", () => {
  it("is the same for the same agent, however the boxes are laid out", () => {
    const a = node("a", { config: { prompt: "p" } }, 0, 0);
    const b = node("b", { config: { description: "d" } }, 100, 100);
    const key = draftKeyOf("Helper", "", [a, b], [edge("a", "b")], { input_schema: [] });
    // the same boxes, moved: new box objects (as the canvas reports them), the same settings
    const moved = [{ ...a, position: { x: 500, y: 40 } }, { ...b, position: { x: -20, y: 9 } }];
    expect(draftKeyOf("Helper", "", moved, [edge("a", "b")], { input_schema: [] })).toBe(key);
  });

  it("changes for every real change: a name, a description, a setting, a connection, the agent's own config", () => {
    const base = draftKeyOf("Helper", "d", [node("a", { config: { prompt: "p" } })], [edge("a", "b")], { x: 1 });
    expect(draftKeyOf("Other", "d", [node("a", { config: { prompt: "p" } })], [edge("a", "b")], { x: 1 })).not.toBe(base);
    expect(draftKeyOf("Helper", "e", [node("a", { config: { prompt: "p" } })], [edge("a", "b")], { x: 1 })).not.toBe(base);
    expect(draftKeyOf("Helper", "d", [node("a", { config: { prompt: "q" } })], [edge("a", "b")], { x: 1 })).not.toBe(base);
    expect(draftKeyOf("Helper", "d", [node("a", { config: { prompt: "p" } })], [edge("a", "c")], { x: 1 })).not.toBe(base);
    expect(draftKeyOf("Helper", "d", [node("a", { config: { prompt: "p" } })], [edge("a", "b")], { x: 2 })).not.toBe(base);
    expect(draftKeyOf("Helper", "d", [node("a", { config: { prompt: "p" } }), node("z", {})], [edge("a", "b")], { x: 1 }), "a new box").not.toBe(base);
  });

  it("does not mix up boxes: the same settings on different boxes are different agents", () => {
    expect(draftKeyOf("n", "", [node("a", { label: "x" }), node("b", { label: "y" })], [], null)).not.toBe(
      draftKeyOf("n", "", [node("a", { label: "y" }), node("b", { label: "x" })], [], null),
    );
  });

  it("turns a box's settings into text once, however often it is asked", () => {
    const data = { label: "Tool", nodeType: "tool", config: { description: "x".repeat(500) } };
    const spy = vi.spyOn(JSON, "stringify");
    const first = dataText(data);
    for (let i = 0; i < 200; i++) dataText(data);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(first).toBe(JSON.stringify(data));
  });

  it("does not turn a box that did not change into text again when another one does", () => {
    const boxes = Array.from({ length: 30 }, (_, i) => node(`t${i}`, { config: { description: `tool ${i} `.repeat(40) } }));
    const edges = boxes.slice(1).map((b) => edge("t0", b.id));
    draftKeyOf("n", "", boxes, edges, null); // the first time: every box is read once

    const spy = vi.spyOn(JSON, "stringify");
    for (let i = 0; i < 100; i++) draftKeyOf("n", "", boxes, edges, null); // e.g. 100 renders of the page
    expect(spy, "100 more renders read nothing again").toHaveBeenCalledTimes(0);

    // one box is edited: it is a new object, the other 29 are the very same objects as before
    const edited = boxes.map((b, i) => (i === 7 ? { ...b, data: { ...b.data, config: { description: "changed" } } } : b));
    const key = draftKeyOf("n", "", edited, edges, null);
    expect(spy, "only the edited box is read").toHaveBeenCalledTimes(1);
    expect(key).not.toBe(draftKeyOf("n", "", boxes, edges, null));
  });

  it("the key the checks use ignores the name and the agent's config, but not the boxes or what connects them", () => {
    const boxes = [node("a", { config: { prompt: "p" } })];
    const base = checkKeyOf("agent_1", boxes, [edge("a", "b")]);
    expect(checkKeyOf("agent_1", [{ ...boxes[0], position: { x: 9, y: 9 } }], [edge("a", "b")]), "moved").toBe(base);
    expect(checkKeyOf("agent_2", boxes, [edge("a", "b")]), "another agent").not.toBe(base);
    expect(checkKeyOf("agent_1", [node("a", { config: { prompt: "q" } })], [edge("a", "b")]), "a setting").not.toBe(base);
    expect(checkKeyOf("agent_1", boxes, []), "a connection").not.toBe(base);
    expect(checkKeyOf(undefined, boxes, [])).toBe(checkKeyOf(undefined, boxes, []));
  });
});
