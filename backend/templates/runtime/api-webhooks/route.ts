/**
 * POST /api/webhooks/[integration] — an outside system calls the application.
 *
 * The integration is one the Blueprint declared with `inbound`; the call is
 * believed only once its signature checks out against the secret the
 * declaration names (read from the environment by NAME), and each delivery
 * is put on the app's own event bus ONCE (`dedupe_key`), where the
 * processes whose `webhook` trigger names its event start. Outside the
 * sign-in gate: the signature is the authentication. Forge runtime — do not
 * remove.
 */
import { NextResponse } from "next/server";
import crypto from "node:crypto";
import { INBOUND } from "@/lib/integrations/connected";
import { PAYMENT_PROVIDERS, PROVIDER_VERIFIERS } from "@/lib/integrations/providers";
import { emitEventAndProcess } from "@/lib/events/bus";
import { initializeRuntime } from "@/lib/runtime-loader";

export const runtime = "nodejs";

/** Seconds a signed timestamp may be from now before the call is stale. */
const TOLERANCE_S = 300;

function sha256(text: string): string {
  return crypto.createHash("sha256").update(text).digest("hex");
}

function same(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

/** `X-Signature: t=<unix seconds>,v1=<hex hmac-sha256 of "<t>.<body>">`. */
export function verifyHmac(raw: string, header: string | null, secret: string, nowS = Math.floor(Date.now() / 1000)):
  { ok: boolean; reason?: string } {
  const parts = Object.fromEntries(String(header ?? "").split(",").map((p) => {
    const [k, ...v] = p.trim().split("=");
    return [k, v.join("=")];
  }));
  const t = Number(parts.t);
  const v1 = String(parts.v1 ?? "");
  if (!Number.isFinite(t) || !v1) return { ok: false, reason: "no signature" };
  if (Math.abs(nowS - t) > TOLERANCE_S) return { ok: false, reason: "stale signature" };
  const expected = crypto.createHmac("sha256", secret).update(`${t}.${raw}`).digest("hex");
  return same(expected, v1) ? { ok: true } : { ok: false, reason: "bad signature" };
}

export async function POST(req: Request, { params }: { params: Promise<{ integration: string }> }) {
  const { integration } = await params;
  const svc = (INBOUND as Record<string, any>)[integration];
  if (!svc) return NextResponse.json({ error: `no integration '${integration}' calls in` }, { status: 404 });
  const raw = await req.text();
  const secret = process.env[String(svc.signingSecretRef)] ?? "";
  if (!secret) {
    return NextResponse.json({ error: `${svc.signingSecretRef} is not set in this environment` }, { status: 503 });
  }
  let eventId = "";
  let type = "";
  if (svc.verify === "bearer") {
    const auth = req.headers.get("authorization") ?? "";
    if (!same(auth, `Bearer ${secret}`)) return NextResponse.json({ error: "bad token" }, { status: 401 });
  } else if (svc.verify === "provider" && PAYMENT_PROVIDERS.has(String(svc.provider))) {
    // A PAYMENT PROVIDER'S CALL IS SETTLED BY ITS ADAPTER: verified, read
    // into the ledger, put on the bus as `<integration>.payment.succeeded`.
    await initializeRuntime();
    const { onProviderCall } = await import("@/lib/payments");
    const out = await onProviderCall(String(svc.provider), integration, raw, req.headers, secret);
    return NextResponse.json(out.body, { status: out.status });
  } else if (svc.verify === "provider") {
    const verifier = PROVIDER_VERIFIERS[String(svc.provider)];
    if (!verifier) return NextResponse.json({ error: `no verifier for ${svc.provider}` }, { status: 501 });
    const v = verifier(raw, req.headers, secret);
    if (!v.ok) return NextResponse.json({ error: v.reason ?? "bad signature" }, { status: 401 });
    eventId = v.eventId ?? "";
    type = v.type ?? "";
  } else {
    const v = verifyHmac(raw, req.headers.get("x-signature") ?? req.headers.get("x-forge-signature"), secret);
    if (!v.ok) return NextResponse.json({ error: v.reason }, { status: 401 });
  }
  let body: any = {};
  try { body = raw ? JSON.parse(raw) : {}; } catch { body = { text: raw }; }
  const named = type || String(body?.type ?? body?.event ?? "received").trim() || "received";
  const event = `${integration}.${named}`;
  const key = `${integration}:${eventId || String(body?.id ?? req.headers.get("x-event-id") ?? "") || sha256(raw)}`;
  await initializeRuntime();
  const put = await emitEventAndProcess(event, {
    entity: integration,
    entityId: body?.id != null ? String(body.id) : null,
    payload: { ...(body && typeof body === "object" ? body : {}), integration, event: named },
    dedupeKey: key,
  });
  if (put && "duplicate" in put) return NextResponse.json({ duplicate: true, event }, { status: 200 });
  if (!put) return NextResponse.json({ error: "the event could not be recorded" }, { status: 500 });
  return NextResponse.json({ accepted: true, event, eventId: put.id }, { status: 202 });
}
