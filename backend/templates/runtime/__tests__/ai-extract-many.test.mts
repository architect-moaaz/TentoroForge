/**
 * `ai_extract` with `aiExtractMany: true` returns every record as a list.
 *
 * SnapIT extracted listings from a page of search results as ONE object —
 * one listing of twenty-five — so nothing could be saved row by row
 * (forge-v3, 2026-09-29). A list comes back as a list, under the names a
 * db_insert fans out over; one record still comes back as one.
 *
 * Run: __tests__/run-extract-many-tests.sh
 */
import { aiExtract } from "../workflows/ai.ts";

let failed = 0;
function eq(actual: unknown, expected: unknown, name: string) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`  ${ok ? "✓" : "✗"} ${name}`);
  if (!ok) { failed++; console.log(`      expected ${JSON.stringify(expected)}\n      actual   ${JSON.stringify(actual)}`); }
}
const g = globalThis as any;
const ctx = () => ({ variables: { crawl: "listing A … listing B" }, input: {}, log: [] }) as any;
const fields = ["title", "url"];

g.__forgeStubResponse = '```json\n[{"title":"Air Max 90","url":"https://a"},{"title":"Air Max 90 White","url":"https://b"}]\n```';
let out: any = await aiExtract({ aiExtractMany: true, aiExtractFields: fields, aiInput: "{{crawl}}" } as any, ctx());
eq(out.count, 2, "every record in the input comes back");
eq(out.output.map((r: any) => r.url), ["https://a", "https://b"], "as a list, under `output`");
eq(out.items, out.output, "and under `items`, which a db_insert fans out over");

g.__forgeStubResponse = '{"results":[{"title":"Only one","url":"https://c"}]}';
out = await aiExtract({ aiExtractMany: true, aiExtractFields: fields, aiInput: "{{crawl}}" } as any, ctx());
eq(out.output, [{ title: "Only one", url: "https://c" }], "a list wrapped in an object is still read");

g.__forgeStubResponse = "no listings here";
out = await aiExtract({ aiExtractMany: "true", aiExtractFields: fields, aiInput: "{{crawl}}" } as any, ctx());
eq(out.output, [], "a reply with no list is an empty list, never a crash");

g.__forgeStubResponse = '{"title":"Air Max 90","url":"https://a"}';
const c1 = ctx();
out = await aiExtract({ aiExtractFields: fields, aiInput: "{{crawl}}" } as any, c1);
eq(out.output, { title: "Air Max 90", url: "https://a" }, "without it, one record as before");
eq(c1.variables.title, "Air Max 90", "with its fields on the variables as before");

console.log(failed ? `\n${failed} failed` : "\nAll ai_extract list tests passed.");
process.exit(failed ? 1 : 0);
