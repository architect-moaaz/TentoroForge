// The app SDK (native) — money. A money field holds MAJOR units (12.50 is twelve
// and a half) in the app's currency; never divide or multiply by 100. The
// currency and locale are the Blueprint's (`config.generated.ts`), the same the
// web reads from `@/lib/money`; a record that carries its own currency passes it.
//
//   formatMoney(row.total)                  // "$1,240.50"
//   formatMoney(row.total, row.currency)    // "£1,240.50"
//
// `<Money value={…} />` (src/ui) is the same as a component.

import { CURRENCY as APP_CURRENCY, LOCALE } from "../config.generated";
import { formatMoney as format } from "./format";

/** The app's currency (ISO 4217). */
export const CURRENCY: string = APP_CURRENCY;

/** `1240.5` -> "$1,240.50" in the app's currency and locale ("" for a missing amount). */
export function formatMoney(amount: number | null | undefined, currency: string = CURRENCY): string {
  return amount === null || amount === undefined ? "" : format(amount, { currency, locale: LOCALE });
}
