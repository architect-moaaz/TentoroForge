/**
 * What an agent "is" for the builder, as text: used to tell whether it changed (so it can save itself) and whether the
 * checks have to run again. Positions and selection are left out on purpose: moving a box is not a change.
 *
 * Turning every box's settings into text is the expensive part (a real agent has dozens of boxes and tens of kilobytes
 * of prompts and tool descriptions), and the page used to do it again for every box on every render, which while a box
 * was being dragged meant many times a second. Each box's `data` is turned into text ONCE and remembered by identity:
 * the page treats `data` as immutable (an edit makes a new object), so the same object is always the same text, and a
 * box that did not change costs nothing.
 */
import type { AgentEdgeSerialized, AgentNodeSerialized } from "@/types/agent-builder";

const textOf = new WeakMap<object, string>();

/** The settings of one box as text, remembered for as long as the same object lives. */
export function dataText(data: unknown): string {
  if (data === null || data === undefined) return "null";
  if (typeof data !== "object") return JSON.stringify(data) ?? "";
  let text = textOf.get(data);
  if (text === undefined) {
    text = JSON.stringify(data);
    textOf.set(data, text);
  }
  return text;
}

const boxes = (nodes: AgentNodeSerialized[]) => nodes.map((n) => `${n.id}\u0001${dataText(n.data)}`).join("\u0002");
const arrows = (edges: AgentEdgeSerialized[]) => edges.map((e) => `${e.source}\u0001${e.target}`).join("\u0002");

/** Has the agent changed? Its name, description, the boxes' settings, what connects to what, and the agent-level config. */
export function draftKeyOf(name: string, description: string, nodes: AgentNodeSerialized[], edges: AgentEdgeSerialized[], config: unknown): string {
  return [name, description, boxes(nodes), arrows(edges), dataText(config ?? null)].join("\u0003");
}

/** What the checks read: the agent's id, the boxes' settings and what connects to what (not the name, not the config). */
export function checkKeyOf(agentId: string | undefined, nodes: AgentNodeSerialized[], edges: AgentEdgeSerialized[]): string {
  return [agentId ?? "", boxes(nodes), arrows(edges)].join("\u0003");
}
