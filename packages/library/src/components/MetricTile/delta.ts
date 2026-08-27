/**
 * One reading of "what did the author mean by this delta".
 *
 * Three shapes reach this component and all three are legitimate:
 *   "+3 vs last week"                  — prose, what the composer authors
 *   { value: "+8% vs last month" }     — the same prose, wrapped
 *   { value: 0.12, direction: "up" }   — the documented numeric contract
 *
 * The component used to bridge them with `parseFloat(delta.value)` and then
 * format the result as a fraction, so "+3 vs last week" rendered as "300%" —
 * a number nobody wrote. Prose is therefore never parsed: it is the author's
 * own words and is passed through untouched. Only a real number is formatted,
 * and only under the documented convention (0.12 == 12%).
 *
 * Direction is inferred from the leading sign when it was not declared, so a
 * fall reads as a fall. It falls back to "flat" rather than undefined —
 * `DELTA_TONE[undefined]` used to put the literal string "undefined" into the
 * tile's className.
 */
export type DeltaDirection = "up" | "down" | "flat";

export interface NormalizedDelta {
  text: string;
  direction: DeltaDirection;
}

export type DeltaInput =
  | string
  | { value?: string | number; direction?: string }
  | null
  | undefined;

function directionFromSign(raw: string | number): DeltaDirection {
  if (typeof raw === "number") {
    if (raw > 0) return "up";
    if (raw < 0) return "down";
    return "flat";
  }
  const first = raw.trim().charAt(0);
  if (first === "+" || first === "↑") return "up";
  // U+2212 MINUS SIGN as well as ASCII hyphen — copy from a spreadsheet gives
  // the former and it would otherwise read as a rise.
  if (first === "-" || first === "−" || first === "↓") return "down";
  return "flat";
}

function asPercent(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent", maximumFractionDigits: 0, signDisplay: "never",
  }).format(Math.abs(value));
}

export function normalizeDelta(input: DeltaInput): NormalizedDelta | null {
  if (input === null || input === undefined || input === "") return null;

  const raw = typeof input === "string" ? input : input.value;
  if (raw === null || raw === undefined || raw === "") return null;

  const declared = typeof input === "object" ? input.direction : undefined;
  const direction: DeltaDirection =
    declared === "up" || declared === "down" || declared === "flat"
      ? declared
      : directionFromSign(raw);

  // A number is the only thing this formats. Prose is the author's, verbatim.
  const text = typeof raw === "number" ? asPercent(raw) : String(raw);
  return { text, direction };
}
