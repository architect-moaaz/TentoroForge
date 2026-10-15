/**
 * How a refusal at the door reads to the person. The platform answers 402
 * with "Not started: …" in the administrator's words; the panel shows it
 * verbatim and says who can change it. Anything else is left as it was.
 */
export const REFUSAL_HINT = "Contact your organisation's administrator to add credit or raise the limit.";

export function describeRefusal(status: number, detail: string | null | undefined, fallback: string): string {
  if (status === 402 && detail) return `${detail} ${REFUSAL_HINT}`;
  return detail || fallback;
}
