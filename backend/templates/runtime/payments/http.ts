/**
 * Where each gateway's API is, and the one way the adapters call it.
 *
 * `FORGE_PAY_EMULATOR` points every call at a local emulator of the
 * gateways (Forge's own end-to-end check); unset — as in every deployed app —
 * the gateways' own addresses are used.
 */
export function apiBase(provider: "stripe" | "razorpay" | "paypal", env?: string): string {
  const emu = String(process.env.FORGE_PAY_EMULATOR ?? "").replace(/\/$/, "");
  const sandbox = String(env ?? "").toLowerCase() !== "live";
  if (emu) return `${emu}/${provider}${provider === "paypal" && sandbox ? "/sandbox" : ""}`;
  if (provider === "stripe") return "https://api.stripe.com";
  if (provider === "razorpay") return "https://api.razorpay.com";
  return sandbox ? "https://api-m.sandbox.paypal.com" : "https://api-m.paypal.com";
}

/** Where a payer is sent for the gateway's own page, when the emulator stands in for it. */
export function emulated(): boolean {
  return Boolean(process.env.FORGE_PAY_EMULATOR);
}

export class GatewayError extends Error {
  status: number;
  body: any;
  constructor(message: string, status: number, body: any) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

/** One call; JSON in and out (or a form body); a non-2xx answer is a GatewayError carrying the gateway's own words. */
export async function call(name: string, url: string, init: { method?: string; headers?: Record<string, string>; json?: unknown; form?: string; timeoutMs?: number }): Promise<any> {
  const headers: Record<string, string> = { Accept: "application/json", ...(init.headers ?? {}) };
  let body: string | undefined;
  if (init.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(init.json); }
  if (init.form !== undefined) { headers["Content-Type"] = "application/x-www-form-urlencoded"; body = init.form; }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), init.timeoutMs ?? 20_000);
  let res: Response;
  try {
    res = await fetch(url, { method: init.method ?? "GET", headers, body, signal: ctrl.signal });
  } catch (err) {
    throw new GatewayError(`${name} could not be reached: ${String((err as Error)?.message ?? err)}`, 0, null);
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  let json: any = {};
  try { json = text ? JSON.parse(text) : {}; } catch { json = { raw: text }; }
  if (!res.ok) {
    const said = json?.error?.description ?? json?.error?.message ?? json?.message ?? json?.error_description
      ?? (typeof json?.error === "string" ? json.error : "") ?? "";
    throw new GatewayError(`${name} answered ${res.status}${said ? `: ${said}` : ""}`, res.status, json);
  }
  return json;
}

export function basic(user: string, password: string): string {
  return "Basic " + Buffer.from(`${user}:${password}`).toString("base64");
}
