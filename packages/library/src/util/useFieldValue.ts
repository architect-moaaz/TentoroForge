"use client";
import * as React from "react";

/**
 * ONE state contract for every input in the library.
 *
 * THE BUG THIS EXISTS TO KILL
 * ---------------------------
 * The library had grown two incompatible contracts and no way to tell which one
 * a component used. Roughly half held their own state and worked when dropped on
 * a page; the other half were fully controlled and expected a parent to supply
 * `value` AND `onChange`. Nothing supplies either when a node is rendered from a
 * page schema — the renderer passes validated props and style, nothing else
 * (`renderer/src/runtime/dispatch.tsx`) — so that half was DEAD:
 *
 *   - Slider: set it to 75, it snaps back to 0. `value={single}` with a handler
 *     that calls an `onChange` nobody passed.
 *   - Rating: click the 4th star, 0 stars fill. `onClick={onChange ? … : undefined}`.
 *   - ColorPicker: set it to #ff0000, it reverts to #000000 — and React logs
 *     "You provided a `value` prop to a form field without an `onChange`
 *     handler", which is what surfaced as the editor's "1 Issue" badge.
 *   - DatePicker / TimePicker: uncontrolled, so typing works, but the value is
 *     stored nowhere and no warning fires. The quiet half of the same split.
 *
 * WHY A HOOK, RATHER THAN THE PATTERN COPIED INTO EACH COMPONENT
 * --------------------------------------------------------------
 * Because per-component divergence IS the bug. Five components each invented
 * their own answer to "am I controlled?" and three of them got it wrong; a
 * sixth (`SegmentedControl`) gates on `value !== undefined` alone, which is the
 * trap described below. Copying a twelve-line block into ten files preserves
 * exactly the conditions that produced the split. One hook makes the contract a
 * thing components *use* rather than a thing they each re-derive.
 *
 * THE CONTRACT
 * ------------
 * Controlled requires BOTH `value` and `onChange`. `value` alone is a
 * declarative INITIAL value — which is the only thing a schema node can express
 * — not a demand to be driven from outside. Gating on `value !== undefined`
 * alone is what made the toggle that cannot be toggled: the registry supplies a
 * default prop, the component decides it is therefore controlled, and it waits
 * forever for an update from a parent that does not exist.
 *
 * The declarative seed is re-read when it changes, so editing the prop in the
 * editor's Properties panel moves the control on the canvas. Without that the
 * `useState` initialiser has already run and the panel edit is invisible.
 *
 * @param value       Controlled value, or the declarative seed when `onChange` is absent.
 * @param onChange    Present only when a real parent owns the state.
 * @param defaultValue Declarative prefill from the schema (`props.defaultValue`).
 * @param fallback    What the component shows when nothing else is supplied.
 */
export function useFieldValue<T>(
  value: T | undefined,
  onChange: ((next: T) => void) | undefined,
  defaultValue: T | undefined,
  fallback: T,
): [T, (next: T) => void] {
  const isControlled = value !== undefined && onChange !== undefined;

  const seed = React.useCallback(
    () => (value !== undefined ? value : defaultValue !== undefined ? defaultValue : fallback),
    // `fallback` is a literal at every call site; excluded so a fresh object or
    // array literal cannot re-seed the field on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [value, defaultValue],
  );

  const [internal, setInternal] = React.useState<T>(seed);

  // Re-seed only when the DECLARATIVE inputs change, and only while
  // uncontrolled. A controlled field's value is already the source of truth, and
  // re-seeding a self-managed field on every render would erase what the user
  // just typed.
  const firstRun = React.useRef(true);
  React.useEffect(() => {
    if (firstRun.current) { firstRun.current = false; return; }
    if (!isControlled) setInternal(seed());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, defaultValue]);

  const current = isControlled ? (value as T) : internal;

  const commit = React.useCallback(
    (next: T) => {
      if (!isControlled) setInternal(next);
      onChange?.(next);
    },
    [isControlled, onChange],
  );

  return [current, commit];
}
