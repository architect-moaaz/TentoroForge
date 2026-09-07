/**
 * Root class for the "control + label on one line" inputs — Checkbox, Switch,
 * RadioGroup.
 *
 * The reported failure: "Switch, Radio, checkbox — They take the complete size,
 * it should be exactly what is required". Their roots were plain
 * `flex items-center gap-2` divs. A div is block-level, so `width: auto` means
 * the parent's full width; and as a flex item of the Stack/Card/Form column they
 * normally live in, `align-items: stretch` stretches them to the full cross-axis
 * width as well. A 36px switch therefore claimed a 1200px row, and the editor's
 * selection outline drew that whole empty row as "the Switch".
 *
 * `w-fit` is the actual fix — an explicit width beats `stretch`, which no amount
 * of `inline-flex` does on its own. `self-start` is belt-and-braces for parents
 * that set `items-stretch` explicitly, `max-w-full` keeps a long label from
 * punching out of a narrow container, and `inline-flex` stops the control from
 * forcing its own line inside prose.
 *
 * Sizing from the Style panel still wins: `resolveStyle(style)` is applied as an
 * inline `style` attribute on the same element, which outranks these classes.
 */
export const CONTROL_ROW_CLASS =
  "inline-flex w-fit max-w-full self-start items-center gap-2" as const;

/** Same contract for the stacked variant (label above a column of options). */
export const CONTROL_COLUMN_CLASS =
  "inline-flex w-fit max-w-full self-start flex-col gap-1.5" as const;
