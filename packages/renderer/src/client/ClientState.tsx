'use client';
import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

import { evaluateComputed } from "../runtime/formInteraction";

/**
 * Values that live on the screen and nowhere else.
 *
 * Every action this platform could express was server-side and record-shaped —
 * run a workflow, or navigate — so an application whose behaviour is arithmetic
 * over what is on screen had no way to be built. A calculator was given a
 * `CalculatorSession` TABLE to hold its display, and every keypress became a
 * server workflow against a row nothing created.
 *
 * The Blueprint declares these as `pageLayout.clientState`; they reach the
 * page schema as `clientState` and are bound as `{{state.<name>}}`, which is
 * why the Engine merges them into its data record under `state` — a binding is
 * a binding, and the renderer needs no new notion of one.
 *
 * Never persisted and never sent anywhere. When the page closes they are gone,
 * which is what "does not store anything" means.
 */
export interface ClientStateValue {
  name: string;
  type: "string" | "number" | "boolean";
  initial?: string | number | boolean;
  description?: string;
}

/** What a control does to the screen's own values when it is pressed. */
export type ClientAction =
  | { kind: "set"; target: string; value: string | number | boolean }
  | { kind: "compute"; target: string; formula: string };

export interface ClientStateController {
  values: Record<string, unknown>;
  set: (name: string, value: unknown) => void;
  run: (action: ClientAction) => void;
}

export const ClientStateContext = createContext<ClientStateController | null>(null);

/** A declared value's starting point — typed, never `undefined`.
 *
 * A display bound to `undefined` renders as nothing, which reads as a broken
 * screen rather than as a calculator showing zero. */
export function initialValues(declared: ClientStateValue[] | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const v of declared ?? []) {
    if (!v || typeof v.name !== "string" || !v.name) continue;
    if (v.initial !== undefined) {
      out[v.name] = v.initial;
      continue;
    }
    out[v.name] = v.type === "number" ? 0 : v.type === "boolean" ? false : "";
  }
  return out;
}

/**
 * The next value a client action produces, or `undefined` when it produces
 * none. Pure, so it can be reasoned about and tested without a component.
 *
 * `compute` runs the same FEEL-lite evaluator a computed form field uses, over
 * the current values — `display + digit`, `number(a) * number(b)`. Nothing new
 * is interpreted, and there is no arbitrary code here by construction.
 */
export function nextValue(
  action: ClientAction,
  values: Record<string, unknown>,
): { target: string; value: unknown } | undefined {
  if (!action || typeof action.target !== "string" || !action.target) return undefined;
  if (action.kind === "set") return { target: action.target, value: action.value };
  if (action.kind === "compute") {
    if (typeof action.formula !== "string" || !action.formula.trim()) return undefined;
    try {
      const computed = evaluateComputed(action.formula, values);
      // A FORMULA THAT CANNOT BE EVALUATED CHANGES NOTHING.
      //
      // `evaluateComputed` signals failure by RETURNING null, not by throwing
      // (formInteraction.ts: an unparseable expression, a hard-error sentinel
      // mapped to null), so catching was never enough — a malformed formula
      // wrote null to the display, and a display bound to null renders as a
      // blank. Ignoring the press is the honest outcome: the screen still
      // shows the last thing it could stand behind.
      if (computed === null || computed === undefined) return undefined;
      return { target: action.target, value: computed };
    } catch {
      return undefined;
    }
  }
  return undefined;
}

/** Whether a value carried on a prop is a client action rather than a handler. */
export function isClientAction(candidate: unknown): candidate is ClientAction {
  if (!candidate || typeof candidate !== "object") return false;
  const kind = (candidate as { kind?: unknown }).kind;
  const target = (candidate as { target?: unknown }).target;
  return (kind === "set" || kind === "compute") && typeof target === "string" && !!target;
}

export function ClientStateProvider({
  declared,
  children,
  onChange,
}: {
  declared?: ClientStateValue[];
  children: React.ReactNode;
  /** Told after every change, so a host holding the binding context (the
   * Engine's `data`) can keep `state` in step with it. */
  onChange?: (values: Record<string, unknown>) => void;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(declared));

  const set = useCallback((name: string, value: unknown) => {
    setValues((prev) => {
      const next = { ...prev, [name]: value };
      onChange?.(next);
      return next;
    });
  }, [onChange]);

  const run = useCallback((action: ClientAction) => {
    setValues((prev) => {
      const got = nextValue(action, prev);
      if (!got) return prev;
      const next = { ...prev, [got.target]: got.value };
      onChange?.(next);
      return next;
    });
  }, [onChange]);

  const controller = useMemo<ClientStateController>(
    () => ({ values, set, run }), [values, set, run]);

  return (
    <ClientStateContext.Provider value={controller}>{children}</ClientStateContext.Provider>
  );
}

export function useClientState(): ClientStateController | null {
  return useContext(ClientStateContext);
}
