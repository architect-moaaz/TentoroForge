/**
 * A stay is found in Mews by what a desk knows of it — a confirmation number,
 * a guest's last name or a room — with direct lookups, and comes back with its
 * guest, room and charged payment (a card one first). Criterion's refund
 * wizard (kkb5mzo3, 2026-11-03) downloaded the hotel's whole reservation list
 * and asked a model to read the match out of it. Runs the SHIPPED mews.ts with
 * Mews and the database stood in.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const g: any = globalThis;
g.__declared = { "mews-pms": { name: "Mews PMS", provider: "mews", keys: ["MEWS_CLIENT_TOKEN"] } };
installHarness({
  stubs: {
    "@/db": "export const db = { execute: async () => ({ rows: [] }) };",
    "drizzle-orm": "export const sql = (...a) => ({ __sql: a });",
    "@/lib/integrations/connected": "export const DECLARED = globalThis.__declared;",
  },
});

const RES = {
  r1: { Id: "r1", Number: "150510", State: "Processed", ScheduledStartUtc: "2026-10-28T14:00:00Z",
        ScheduledEndUtc: "2026-10-30T10:00:00Z", AccountId: "c1", AssignedResourceId: "room-314" },
  r2: { Id: "r2", Number: "150400", State: "Started", ScheduledStartUtc: "2026-11-02T14:00:00Z",
        ScheduledEndUtc: "2026-11-05T10:00:00Z", AccountId: "c1", AssignedResourceId: null },
};
const sent: { op: string; body: any }[] = [];
g.fetch = async (url: string, init: any) => {
  const op = url.split("/api/connector/v1/")[1];
  const body = JSON.parse(init.body);
  sent.push({ op, body });
  const reply = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "content-type": "application/json" } });
  if (op === "reservations/getAll/2023-06-06") {
    if (body.Numbers) return reply({ Reservations: Object.values(RES).filter((r) => body.Numbers.includes(r.Number)) });
    if (body.AccountIds) return reply({ Reservations: Object.values(RES).filter((r) => body.AccountIds.includes(r.AccountId)) });
    if (body.AssignedResourceIds) {
      ok(Boolean(body.CollidingUtc?.StartUtc && body.CollidingUtc?.EndUtc), "a room's stays are looked for in a window");
      return reply({ Reservations: Object.values(RES).filter((r) => body.AssignedResourceIds.includes(r.AssignedResourceId)) });
    }
  }
  if (op === "customers/getAll") {
    const all = [{ Id: "c1", FirstName: "Ana", LastName: "Sorlito", Email: "ana@example.com" }];
    if (body.LastNames) return reply({ Customers: all.filter((c) => body.LastNames.includes(c.LastName)) });
    return reply({ Customers: all.filter((c) => (body.CustomerIds ?? []).includes(c.Id)) });
  }
  if (op === "resources/getAll") {
    const all = [{ Id: "room-314", Name: "314" }];
    if (body.Names) return reply({ Resources: all.filter((r) => body.Names.includes(r.Name)) });
    return reply({ Resources: all.filter((r) => (body.ResourceIds ?? []).includes(r.Id)) });
  }
  if (op === "payments/getAll") {
    return reply({ Payments: [
      { Id: "p-cash", ReservationId: "r1", State: "Charged", Type: "CashPayment", BillId: "b0",
        Amount: { Currency: "GBP", GrossValue: -20 } },
      { Id: "p-card", ReservationId: "r1", State: "Charged", Type: "CreditCardPayment", BillId: "b1",
        Amount: { Currency: "GBP", GrossValue: -93.14 }, Data: { CreditCard: { ObfuscatedNumber: "************4412" } } },
      { Id: "p-failed", ReservationId: "r2", State: "Failed", Type: "CreditCardPayment", Amount: { Currency: "GBP", GrossValue: -5 } },
    ] });
  }
  return new Response(JSON.stringify({ Message: `unexpected ${op}` }), { status: 400 });
};

process.env.MEWS_CLIENT_TOKEN = "ct-integration";
process.env.MEWS_ACCESS_TOKEN = "at-single-hotel";
delete process.env.MEWS_ENVIRONMENT;
const mews: any = await import("../mews.ts");

// ── By confirmation number ─────────────────────────────────────────────────
const byNumber = await mews.findStays("150510");
eqJson(byNumber.map((s: any) => s.reservationId), ["r1"], "a confirmation number finds its stay");
const s = byNumber[0];
eqJson([s.guestName, s.guestEmail, s.roomNumber, s.arrivalDate, s.departureDate, s.reservationStatus, s.confirmationNumber],
       ["Ana Sorlito", "ana@example.com", "314", "2026-10-28", "2026-10-30", "Processed", "150510"],
       "with its guest, room, dates and state");
eqJson(s.payment, { id: "p-card", amount: 93.14, currency: "GBP", kind: "Card", cardLast4: "4412", billId: "b1" },
       "and its charged card payment, before a cash one");
eqJson([s.billId, s.accountId, s.customerId], ["b1", "c1", "c1"], "its bill, account and guest ids");
const signed = sent.find((x) => x.op === "reservations/getAll/2023-06-06")!.body;
eqJson([signed.ClientToken, signed.AccessToken], ["ct-integration", "at-single-hotel"], "signed with the organisation's own connection");
ok(!sent.some((x) => x.op === "reservations/getAll/2023-06-06" && !x.body.Numbers && !x.body.AccountIds && !x.body.AssignedResourceIds),
   "never the whole reservation list");

// ── By last name, any case ─────────────────────────────────────────────────
const byName = await mews.findStays("sorlito");
eqJson(byName.map((x: any) => x.reservationId), ["r2", "r1"], "a last name finds the guest's stays, newest first");
eqJson(byName[0].payment, null, "a stay whose only payment failed has none");

// ── By room ────────────────────────────────────────────────────────────────
const byRoom = await mews.findStays("314");
eqJson(byRoom.map((x: any) => x.reservationId), ["r1"], "a room finds the stay in it");

// ── Nothing asked, nothing found ───────────────────────────────────────────
eqJson(await mews.findStays("   "), [], "an empty search asks Mews nothing");
eqJson(await mews.findStays("nobody"), [], "no match is an empty list, not an error");
done("a-stay-is-found-in-mews");
