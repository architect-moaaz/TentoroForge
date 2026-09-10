"use client";

/**
 * Literal / bound switch for a single prop.
 *
 * WHY it names the prop and carries a word: the button used to be a bare "Aa"
 * with a `title` and nothing else (docs/editor-audit — Phase 7 papercut). A
 * `title` is a mouse-only affordance: screen readers announced the button as
 * "Aa", and a panel of twelve identical "Aa" buttons gave no way to tell which
 * prop each one belonged to. "Aa" also does not read as "bind" to anyone who
 * has not been told. The glyph stays (it is the compact state marker the panel
 * is laid out for) but it now sits next to the word for the CURRENT mode, and
 * the accessible name says both the prop and what clicking does.
 *
 * `aria-pressed` makes it a real toggle rather than a button whose meaning the
 * user has to infer from the colour.
 */
export function BindToggle({
  isBound, onToggle, propName,
}: { isBound: boolean; onToggle: () => void; propName?: string }) {
  const subject = propName ? `${propName}: ` : "";
  const description = isBound
    ? `${subject}bound to data — click to use a literal value`
    : `${subject}literal value — click to bind to data`;
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={isBound}
      aria-label={description}
      title={description}
      className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ${
        isBound ? "bg-blue-500 text-white" : "border bg-muted/40 hover:bg-muted"
      }`}
    >
      <span aria-hidden="true" className="font-mono">{isBound ? "{ }" : "Aa"}</span>
      <span aria-hidden="true" className="uppercase tracking-wide">
        {isBound ? "bound" : "value"}
      </span>
    </button>
  );
}
