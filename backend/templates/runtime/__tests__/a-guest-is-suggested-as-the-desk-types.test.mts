/**
 * A guest is suggested as the desk types — part of a name, an email, the start
 * of a confirmation number or a room — from the stays the application keeps,
 * and who is in the hotel now from Mews. Mews matches a last name only exactly
 * and its name search sees only the guests in house, so Criterion's desk
 * (kkb5mzo3, 2026-11-03) could not find a guest who had left by typing "kios".
 * Runs the SHIPPED mews.ts; Mews and the database are stood in.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const g: any = globalThis;
g.__declared = { "mews-pms": { name: "Mews PMS", provider: "mews", keys: ["MEWS_CLIENT_TOKEN"] } };

// ── the database, by the statements mews.ts makes ──────────────────────────
const stays = new Map<string, any>();
const sync = new Map<string, any>();
const sqlOf = (q: any): { text: string; values: any[] } => {
  const values: any[] = [];
  const walk = (node: any): string => {
    if (!node || !node.__sql) { values.push(node); return "$"; }
    const [strings, ...vals] = node.__sql;
    return strings.map((s: string, i: number) => s + (i < vals.length ? walk(vals[i]) : "")).join("");
  };
  return { text: walk(q).replace(/\s+/g, " ").trim(), values };
};
const ilike = (v: unknown, pattern: string) =>
  new RegExp("^" + pattern.replace(/\\([\\%_])|[%_]|[.*+?^${}()|[\]]/g,
    (m, esc) => esc ? "\\" + esc : m === "%" ? ".*" : m === "_" ? "." : "\\" + m) + "$", "i").test(String(v ?? ""));
g.__execute = async (q: any) => {
  const { text, values: v } = sqlOf(q);
  if (text.startsWith("CREATE TABLE") || text.startsWith("ALTER TABLE")) return { rows: [] };
  if (text.startsWith("SELECT id FROM forge_mews_properties")) return { rows: [] };
  if (text.startsWith("SELECT synced_through")) return { rows: sync.has(v[0]) ? [sync.get(v[0])] : [] };
  if (text.startsWith("SELECT 1 AS one FROM forge_mews_stays"))
    return { rows: [...stays.values()].some((s) => s.connection === v[0]) ? [{ one: 1 }] : [] };
  if (text.startsWith("INSERT INTO forge_mews_sync (connection, pending")) {
    sync.set(v[0], { ...(sync.get(v[0]) ?? {}), pending: v[1], last_run_at: new Date().toISOString() });
    return { rows: [] };
  }
  if (text.startsWith("INSERT INTO forge_mews_stays")) {
    const [reservation_id, connection, confirmation_number, state, arrival_date, departure_date, customer_id,
           account_id, guest_name, guest_email, room_number, bill_id, payment] = v;
    stays.set(reservation_id, { reservation_id, connection, confirmation_number, state, arrival_date, departure_date,
                                customer_id, account_id, guest_name, guest_email, room_number, bill_id, payment });
    return { rows: [] };
  }
  if (text.startsWith("INSERT INTO forge_mews_sync")) {
    const [connection, through, error, count] = v;
    const prev = sync.get(connection) ?? {};
    sync.set(connection, { ...prev, synced_through: through ?? prev.synced_through ?? null,
                           last_run_at: new Date().toISOString(), last_error: error, stays: count });
    return { rows: [] };
  }
  if (text.startsWith("DELETE FROM forge_mews_stays")) {
    for (const [id, s] of stays) if (s.connection === v[0] && String(s.departure_date) < String(v[1])) stays.delete(id);
    return { rows: [] };
  }
  if (text.startsWith("SELECT * FROM forge_mews_stays")) {
    const [connection, like, like2, starts, room, startsAgain, limit] = v;
    const rows = [...stays.values()].filter((s) => s.connection === connection && (
      ilike(s.guest_name, like) || ilike(s.guest_email, like2) || ilike(s.confirmation_number, starts)
      || String(s.room_number ?? "").toLowerCase() === String(room).toLowerCase()));
    rows.sort((a, b) => Number(ilike(b.guest_name, startsAgain)) - Number(ilike(a.guest_name, startsAgain))
                        || String(b.arrival_date).localeCompare(String(a.arrival_date)));
    return { rows: rows.slice(0, limit) };
  }
  throw new Error(`unexpected statement: ${text}`);
};
installHarness({
  stubs: {
    "@/db": "export const db = { execute: (q) => globalThis.__execute(q) };",
    "drizzle-orm": "export const sql = (...a) => ({ __sql: a });",
    "@/lib/integrations/connected": "export const DECLARED = globalThis.__declared;",
  },
});

// ── Mews ───────────────────────────────────────────────────────────────────
const day = (d: number) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10) + "T14:00:00Z";
const reservations = [
  { Id: "r-left", Number: "150510", State: "Processed", ScheduledStartUtc: day(-3), ScheduledEndUtc: day(-1), AccountId: "c-kiosk", AssignedResourceId: "room-314", UpdatedUtc: day(-1) },
  { Id: "r-old", Number: "140001", State: "Processed", ScheduledStartUtc: day(-40), ScheduledEndUtc: day(-38), AccountId: "c-smith", AssignedResourceId: null, UpdatedUtc: day(-38) },
  { Id: "r-soon", Number: "160002", State: "Confirmed", ScheduledStartUtc: day(5), ScheduledEndUtc: day(7), AccountId: "c-smith", AssignedResourceId: null, UpdatedUtc: day(-2) },
];
const customers = [
  { Id: "c-kiosk", FirstName: "Tokyo", LastName: "KioskTest853002", Email: "kiosk@example.com" },
  { Id: "c-smith", FirstName: "Ana", LastName: "Smith", Email: "ana.smith@example.com" },
  { Id: "c-inhouse", FirstName: "Walk", LastName: "Inman", Email: null },
  { Id: "c-hart", FirstName: "Amelia", LastName: "Hart", Email: "amelia.hart@example.com" },
];
// What Mews says changed since a pass: the first time, a cancellation.
let changed: any[] = [{ ...reservations[0], State: "Canceled" }];
const asked: { op: string; body: any }[] = [];
g.fetch = async (url: string, init: any) => {
  const op = url.split("/api/connector/v1/")[1];
  const body = JSON.parse(init.body);
  asked.push({ op, body });
  const reply = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "content-type": "application/json" } });
  if (op === "reservations/getAll/2023-06-06") {
    if (body.AccountIds) {
      const extra = body.AccountIds.includes("c-inhouse")
        ? [{ Id: "r-inhouse", Number: "170003", State: "Started", ScheduledStartUtc: day(0), ScheduledEndUtc: day(2), AccountId: "c-inhouse" }] : [];
      return reply({ Reservations: [...reservations, ...extra].filter((r) => body.AccountIds.includes(r.AccountId)) });
    }
    // Two pages the first time; what changed after.
    if (body.UpdatedUtc) return reply({ Reservations: changed, Cursor: null });
    if (!body.Limitation?.Cursor) return reply({ Reservations: reservations.slice(0, 2), Cursor: "page-2" });
    return reply({ Reservations: reservations.slice(2), Cursor: null });
  }
  if (op === "customers/getAll") return reply({ Customers: customers.filter((c) => (body.CustomerIds ?? []).includes(c.Id)) });
  if (op === "resources/getAll") return reply({ Resources: [{ Id: "room-314", Name: "314" }].filter((r) => (body.ResourceIds ?? []).includes(r.Id)) });
  if (op === "payments/getAll") return reply({ Payments: [{ Id: "p1", ReservationId: "r-left", State: "Charged", Type: "CreditCardPayment", BillId: "b1", Amount: { Currency: "GBP", GrossValue: -93.14 } }] });
  if (op === "customers/search") return reply({ Customers: /inm/i.test(body.Name) ? [{ Customer: { Id: "c-inhouse" } }] : [] });
  return new Response(JSON.stringify({ Message: `unexpected ${op}` }), { status: 400 });
};
process.env.MEWS_CLIENT_TOKEN = "ct";
process.env.MEWS_ACCESS_TOKEN = "at";
const mews: any = await import("../mews.ts");

// ── the first sync keeps the window, carrying on where it stopped ──────────
const cut = await mews.syncStays(undefined, { budgetMs: 0 });
eqJson([cut.stays, cut.complete], [2, false], "a pass out of time keeps the page it read");
eqJson(JSON.parse(sync.get("organisation").pending).cursor, "page-2", "and remembers where it stopped");
const first = await mews.syncStays();
eqJson([first.stays, first.complete, first.error], [1, true, null], "the next pass reads on from there, not from page one");
ok(asked.filter((a) => a.op === "reservations/getAll/2023-06-06").pop()!.body.Limitation.Cursor === "page-2",
   "with the cursor it stopped at");
eqJson(stays.size, 3, "every stay in the window is kept");
eqJson(sync.get("organisation").pending, null, "a finished pass leaves nothing pending");
const firstAsk = asked.find((a) => a.op === "reservations/getAll/2023-06-06")!.body;
ok(Boolean(firstAsk.CollidingUtc?.StartUtc && firstAsk.CollidingUtc?.EndUtc) && !firstAsk.UpdatedUtc, "by the stays in the window");
eqJson(stays.get("r-left")?.guest_name, "Tokyo KioskTest853002", "each kept with its guest");
eqJson(JSON.parse(stays.get("r-left")?.payment).amount, 93.14, "and its charged payment");

// ── typing part of a name finds a guest who has left ───────────────────────
const typed = await mews.suggestStays("kios");
eqJson(typed.stays.map((s: any) => s.reservationId), ["r-left"], "\"kios\" finds the guest who left two days ago");
eqJson([typed.stays[0].roomNumber, typed.stays[0].payment.amount], ["314", 93.14], "with the room and payment a pick needs");
eqJson((await mews.suggestStays("smi")).stays.map((s: any) => s.reservationId), ["r-soon", "r-old"],
       "a name with two stays offers both, newest first");
eqJson((await mews.suggestStays("1505")).stays.map((s: any) => s.reservationId), ["r-left"], "the start of a confirmation number");
eqJson((await mews.suggestStays("314")).stays.map((s: any) => s.reservationId), ["r-left"], "a room");
eqJson((await mews.suggestStays("ana.smith@")).stays.length, 2, "an email");
ok(!asked.some((a) => a.op === "customers/search" && a.body.Name === "1505"), "a number is never put to the name search");

// ── who arrived since the last sync, from Mews ─────────────────────────────
const inHouse = await mews.suggestStays("inma");
eqJson(inHouse.stays.map((s: any) => s.reservationId), ["r-inhouse"], "a guest the sync has not kept yet, from Mews's name search");
const before = asked.length;
await mews.suggestStays("inma");
ok(asked.length === before, "asked again within seconds, Mews is not asked twice");

// ── after that, only what changed ──────────────────────────────────────────
const next = await mews.syncStays();
const nextAsk = asked.filter((a) => a.op === "reservations/getAll/2023-06-06").pop()!.body;
ok(Boolean(nextAsk.UpdatedUtc?.StartUtc) && !nextAsk.CollidingUtc, "the next sync asks only for what changed since");
eqJson([next.stays, stays.get("r-left")?.state], [1, "Canceled"], "and keeps the change");

// ── no cron tick: a search brings stale kept stays up to date ──────────────
// A test deployment runs no scheduled jobs, so a booking made after the first
// pass never reached the Guest field (kkb5mzo3, 2026-11-03).
changed = [{ Id: "r-hart", Number: "12", State: "Confirmed", ScheduledStartUtc: day(9), ScheduledEndUtc: day(10),
             AccountId: "c-hart", AssignedResourceId: null, UpdatedUtc: day(0) }];
const fresh = asked.length;
eqJson((await mews.suggestStays("amel")).stays.length, 0, "kept stays a minute old are not refreshed on every keystroke");
ok(!asked.slice(fresh).some((a) => a.op === "reservations/getAll/2023-06-06" && a.body.UpdatedUtc),
   "and Mews is not asked for changes");
sync.set("organisation", { ...sync.get("organisation"), last_run_at: new Date(Date.now() - 10 * 60_000).toISOString() });
const late = await Promise.all([mews.suggestStays("amel"), mews.suggestStays("amel")]);
eqJson(late[0].stays.map((s: any) => [s.reservationId, s.guestName]), [["r-hart", "Amelia Hart"]],
       "kept stays ten minutes old are refreshed first, and the new booking is suggested");
eqJson(late[0].refreshed, true, "saying it refreshed");
eqJson(asked.slice(fresh).filter((a) => a.op === "reservations/getAll/2023-06-06" && a.body.UpdatedUtc).length, 1,
       "two searches at once refresh once");
done("a-guest-is-suggested-as-the-desk-types");
