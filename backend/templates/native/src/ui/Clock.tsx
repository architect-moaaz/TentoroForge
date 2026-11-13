// A clock that does not cost the screen. A map screen is heavy (a map, a sheet, panels), so it must NEVER hold a ticking
// `now` in its own state: a timer that sets state at the screen re-draws the whole map on every tick, and a slow phone
// falls behind, then draws without rest. The tick lives in these small parts, so only the number being changed is drawn.
//
//   <Countdown until={offer.requestExpiresAt} />        2:41 (a request's own expiry; nothing is drawn without one)
//   <Elapsed since={driver.onlineSince} />               12 min
//   const gone = useExpired(offer.requestExpiresAt);     false until that moment, then true: ONE re-draw, no ticking
import * as React from "react";
import { Text, type TextProps } from "./Text";
import { countdownText, elapsedText, msUntil } from "./logic";

/** A number that follows the clock, drawn by this part alone. */
function useTick(everyMs: number, on: boolean): number {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(t);
  }, [everyMs, on]);
  return now;
}

/** True once an ISO time has passed. It sets ONE timer for the moment itself, so the screen draws once when it arrives. */
export function useExpired(at: string | null | undefined): boolean {
  const [, bump] = React.useReducer((n: number) => n + 1, 0);
  const left = msUntil(at, Date.now());
  React.useEffect(() => {
    if (left === null || left <= 0) return;
    const t = setTimeout(bump, Math.min(left + 50, 2_147_000_000));
    return () => clearTimeout(t);
  }, [at]);
  return left !== null && left <= 0;
}

export function Countdown({ until, ...text }: { until: string | null | undefined } & Omit<TextProps, "children">) {
  const now = useTick(1000, Boolean(until));
  const left = msUntil(until, now);
  if (left === null) return null;
  return <Text {...text}>{countdownText(left)}</Text>;
}

export function Elapsed({ since, ...text }: { since: string | null | undefined } & Omit<TextProps, "children">) {
  const now = useTick(30000, Boolean(since));
  const ago = msUntil(since, now);
  if (ago === null) return null;
  return <Text {...text}>{elapsedText(-ago)}</Text>;
}
