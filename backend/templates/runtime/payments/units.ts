/**
 * Money in major units (what people read: 12.50) and minor units (what a
 * gateway is sent: 1250), per ISO 4217. Most currencies have two decimals;
 * some have none (JPY: 1200 yen is 1200), and the Gulf's dinars and rials
 * have three (KWD 1.250 is 1250 fils) — sent rounded to the ten, as Stripe
 * and Razorpay require.
 */
export const ZERO_DECIMAL = new Set(["BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"]);
export const THREE_DECIMAL = new Set(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"]);

export function toMinor(amount: number, currency: string): number {
  const c = String(currency).toUpperCase();
  if (ZERO_DECIMAL.has(c)) return Math.round(amount);
  if (THREE_DECIMAL.has(c)) return Math.round(amount * 100) * 10;
  return Math.round(amount * 100);
}

export function toMajor(amountMinor: number, currency: string): number {
  const c = String(currency).toUpperCase();
  if (ZERO_DECIMAL.has(c)) return amountMinor;
  if (THREE_DECIMAL.has(c)) return amountMinor / 1000;
  return amountMinor / 100;
}

/** Decimals a currency is written with. */
export function decimals(currency: string): number {
  const c = String(currency).toUpperCase();
  return ZERO_DECIMAL.has(c) ? 0 : THREE_DECIMAL.has(c) ? 3 : 2;
}
