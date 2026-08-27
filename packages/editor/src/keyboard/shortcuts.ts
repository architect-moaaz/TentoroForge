export type Shortcut = {
  key: string;        // single character, lowercase
  meta?: boolean;
  shift?: boolean;
  alt?: boolean;
  ctrl?: boolean;
};

export function matches(e: KeyboardEvent, sc: Shortcut): boolean {
  return (
    e.key.toLowerCase() === sc.key &&
    !!e.metaKey === !!sc.meta &&
    !!e.shiftKey === !!sc.shift &&
    !!e.altKey === !!sc.alt &&
    !!e.ctrlKey === !!sc.ctrl
  );
}
