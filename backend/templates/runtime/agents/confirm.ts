/**
 * Confirm before changing — enforced in code, not asked politely. Forge runtime — do not remove.
 *
 * A tool that changes data (`spec.confirm`) does not run the first time the assistant calls it. The call is HELD:
 * nothing happens, the assistant is told to say exactly what it is about to do and ask. It runs only when the
 * person has pressed Go ahead on THAT hold (the chat widget sends the hold's id with the press) and the assistant
 * then makes the very same call in that turn. Words typed in the chat are never a yes: they are not read at all,
 * in any language, so "sure", "no" and "kinda" all leave the change held. The assistant cannot confirm on the
 * person's behalf either: it cannot press a button, a hold and its release can never be in the same turn, and a
 * call whose input differs even slightly is a new hold.
 *
 * Holds live with the conversation (so they survive separate requests) and lapse after HOLD_MINUTES or one
 * turn. Pure functions: no I/O, tested on their own.
 */
import type { AgentToolSpec, ConfirmSignal, ConfirmState } from "./types";

const HOLD_ID = /^[0-9a-zA-Z-]{8,64}$/;

/** The button press in a chat request's body, or null. Anything that is not exactly that shape is ignored, never guessed at. */
export function confirmSignalOf(raw: unknown): ConfirmSignal | null {
  const c = raw as { holdId?: unknown; decision?: unknown } | null;
  if (!c || typeof c !== "object") return null;
  if (typeof c.holdId !== "string" || !HOLD_ID.test(c.holdId)) return null;
  if (c.decision !== "confirm" && c.decision !== "cancel") return null;
  return { holdId: c.holdId, decision: c.decision };
}

export const HOLD_MINUTES = 15;
const MAX_HOLDS = 10;

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

/** The change in a line the assistant can repeat to the person. */
export function describeChange(spec: AgentToolSpec, input: unknown): string {
  const what = spec.name.replace(/[_-]+/g, " ");
  const text = stableStringify(input ?? {});
  return `${what} with ${text.length > 300 ? `${text.slice(0, 300)}…` : text}`;
}

export type Gate =
  | { run: true }
  | { run: false; held: { held: true; needs_confirmation: true; holdId: string; message: string } }
  | { run: false; refused: string };

const newHoldId = (): string => globalThis.crypto.randomUUID();

/**
 * Decide whether this call may run now. Changes `state` in place (the caller saves it). `state.turn` is THIS
 * turn's number: a hold made last turn has `turn === state.turn - 1`. `ctx.confirm` is the button the person
 * pressed with this message, if any: the only thing that can release (or cancel) a hold.
 */
export function gate(state: ConfirmState, spec: AgentToolSpec, input: unknown, ctx: { now: number; confirm?: ConfirmSignal | null }): Gate {
  if (!spec.confirm) return { run: true };
  const key = actionKey(spec.name, input);
  state.holds = state.holds.filter((h) => ctx.now - h.at <= HOLD_MINUTES * 60_000 && h.turn >= state.turn - 1);

  const i = state.holds.findIndex((h) => h.key === key && h.turn === state.turn - 1);
  const asked = i >= 0 ? state.holds[i] : null;
  // Only a press on THIS hold counts. A typed reply, or a press made for some other hold, answers nothing here.
  if (asked?.id && ctx.confirm && ctx.confirm.holdId === asked.id) {
    state.holds.splice(i, 1);
    if (ctx.confirm.decision === "cancel") {
      return { run: false, refused: "The person cancelled, so nothing was changed. Do not try again unless they ask. Ask what they would like instead." };
    }
    return { run: true };
  }

  // Asked again in the same turn: it is the same question, so keep its id (the one already shown to the person).
  const same = state.holds.find((h) => h.key === key && h.turn === state.turn);
  const holdId = same?.id ?? newHoldId();
  const summary = describeChange(spec, input);
  state.holds = [...state.holds.filter((h) => h.key !== key), { id: holdId, tool: spec.name, key, summary, at: ctx.now, turn: state.turn }].slice(-MAX_HOLDS);
  return {
    run: false,
    held: {
      held: true,
      needs_confirmation: true,
      holdId,
      message:
        `Nothing has been changed yet: this changes data, so the person has to agree first. Tell them plainly what you are about to do (${summary}) ` +
        `and tell them to press the Go ahead button under your message to agree, or Cancel. Typing yes does not count: only the button does, so do not ask them to type it. ` +
        `Do not call ${spec.name} again in this reply. When they have pressed Go ahead, call it again with exactly the same input.`,
    },
  };
}
