/**
 * A read that failed is said, not hidden — from the SHIPPED src/sdk/server.ts.
 *
 * "Add a child" saved every child; "My Children" showed none. The list read
 * failed on "Unknown entity: Child", the SDK returned [] without a word, and
 * every check saw a tidy empty page (forge-v3, 2026-09-27). A record that is
 * simply not there stays a quiet null.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const g = globalThis as any;
g.__reports = [];
installHarness({
  stubs: {
    "@/auth": "export const auth = async () => ({ user: { id: 'u1', role: 'Parent' } });",
    "@/lib/data-engine": `
      export const query = async (e) => { if (e === 'Child') throw new Error('Unknown entity: Child'); return { data: [{ id: 'd1' }], total: 1 }; };
      export const findById = async (e, id) => {
        if (id === 'gone') { const err = new Error('not found'); err.name = 'NotFoundError'; throw err; }
        throw new Error('Unknown entity: ' + e);
      };`,
    "@/lib/data-engine-bridge": "export const actorCtx = (u) => u ?? {}; export const resolveAggregate = async () => 0; export const resolveQuery = async () => ({}); export const resolveSeries = async () => []; export const resolveSimilar = async () => [];",
    "@/lib/data-init": "export const ensureDataEngineInitialized = async () => {};",
    "./schema": "export const NUMERIC_FIELDS = {}; export const READABLE_FIELDS = {};",
    "@/lib/account": "export const ACCOUNT = null;",
    "./geo": "export const distanceKm = () => 0; export const formatDistance = () => ''; export const parseNear = () => null; export const isPoint = () => false;",
    "./widgets": "export default {};",
    "@/lib/error_reporter": "export const reportFromError = (err, base) => { globalThis.__reports.push({ message: String(err?.message ?? err), ...base }); };",
    "next/headers": "export const cookies = async () => ({ get: () => undefined });",
  },
});

const printed: string[] = [];
const was = console.error;
console.error = (...a: unknown[]) => { printed.push(a.map(String).join(" ")); };
const sdk: any = await import("../../app-foundation/src/sdk/server.ts");

const children = await sdk.listPage("Child", {});
eqJson(children.rows, [], "the page still gets an empty list rather than a crash");
ok(printed.some((l) => l.startsWith("[forge:swallowed] list Child failed: Unknown entity: Child")),
   "the failed list read is printed where the build's checks read the server");

const missing = await sdk.record("Doctor", "gone");
ok(missing === null, "a record that is not there is null");
const quietBefore = printed.length;

const broken = await sdk.record("Child", "c-1");
ok(broken === null, "a record that could not be read is null to the page");
ok(printed.length === quietBefore + 1 && printed.at(-1)!.includes("[forge:swallowed] record Child failed"),
   "but its failure is printed, and the missing one was not");

await new Promise((r) => setTimeout(r, 20));                      // the report is sent asynchronously
const messages = g.__reports.map((r: any) => r.message);
ok(messages.includes("Unknown entity: Child"), "and both failures reach Smith through the error reporter");
ok(!messages.includes("not found"), "a record that is not there is not reported");
console.error = was;
done("a read that failed is said");
