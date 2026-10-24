/**
 * Confirm before changing — enforced in code, not asked politely. Forge runtime — do not remove.
 *
 * A tool that changes data (`spec.confirm`) does not run the first time the assistant calls it. The call is HELD:
 * nothing happens, the assistant is told to say exactly what it is about to do and ask. It runs only when the
 * assistant makes the very same call in the turn right AFTER the person has replied, and that reply is not a "no".
 * So the assistant cannot confirm on the person's behalf: a hold and its release can never be in the same turn,
 * and a call whose input differs even slightly is a new hold.
 *
 * Holds live with the conversation (so they survive separate requests) and lapse after HOLD_MINUTES or one
 * turn. Pure functions: no I/O, tested on their own.
 */
import type { AgentToolSpec, ConfirmState } from "./types";

export const HOLD_MINUTES = 15;
const MAX_HOLDS = 10;
const DECLINE = /^\s*(no|nope|nah|cancel|stop|don'?t|do not|wait|hold on|never ?mind|not now|not yet|abort)\b/i;

/** JSON with sorted keys, so the same input always gives the same text. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    return `{${Object.keys(o)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export const actionKey = (tool: string, input: unknown): string => `${tool}:${stableStringify(input ?? {})}`;

/** Whether the person's reply says no. Anything else is taken as going ahead. */
export const declined = (reply: string): boolean => DECLINE.test(reply);

/** The change in a line the assistant can repeat to the person. */
export function describeChange(spec: AgentToolSpec, input: unknown): string {
  const what = spec.name.replace(/[_-]+/g, " ");
  const text = stableStringify(input ?? {});
  return `${what} with ${text.length > 300 ? `${text.slice(0, 300)}…` : text}`;
}

export type Gate =
  | { run: true }
  | { run: false; held: { held: true; needs_confirmation: true; message: string } }
  | { run: false; refused: string };

/**
 * Decide whether this call may run now. Changes `state` in place (the caller saves it). `state.turn` is THIS
 * turn's number: a hold made last turn has `turn === state.turn - 1`.
 */
export function gate(state: ConfirmState, spec: AgentToolSpec, input: unknown, ctx: { now: number; reply: string }): Gate {
  if (!spec.confirm) return { run: true };
  const key = actionKey(spec.name, input);
  state.holds = state.holds.filter((h) => ctx.now - h.at <= HOLD_MINUTES * 60_000 && h.turn >= state.turn - 1);

  const i = state.holds.findIndex((h) => h.key === key && h.turn === state.turn - 1);
  if (i >= 0) {
    state.holds.splice(i, 1);
    if (declined(ctx.reply)) {
      return { run: false, refused: "The person said no, so nothing was changed. Do not try again unless they ask. Ask what they would like instead." };
    }
    return { run: true };
  }

  const summary = describeChange(spec, input);
  state.holds = [...state.holds.filter((h) => h.key !== key), { tool: spec.name, key, summary, at: ctx.now, turn: state.turn }].slice(-MAX_HOLDS);
  return {
    run: false,
    held: {
      held: true,
      needs_confirmation: true,
      message:
        `Nothing has been changed yet: this changes data, so the person has to agree first. Tell them plainly what you are about to do (${summary}) ` +
        `and ask them to confirm. Do not call ${spec.name} again in this reply. When they answer and agree, call it again with exactly the same input.`,
    },
  };
}
