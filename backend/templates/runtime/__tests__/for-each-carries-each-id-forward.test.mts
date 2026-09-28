/**
 * The `for_each` step, run from the SHIPPED workflows/index.ts, against an
 * in-memory database that really stores rows.
 *
 * SnapIT's listings each need a merchant (found by domain, else created), a
 * merchant product pointing at it, and a search result pointing at both. The
 * engine had no per-item step, so the workflow could not be written at all
 * (forge-v3, 2026-09-29).
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const noop = "export default {}; export const __noop = true;";
(globalThis as any).__rows = { merchants: [], merchant_products: [], search_results: [] } as Record<string, any[]>;
installHarness({
  stubs: {
    "@/db": `
      let n = 0;
      const match = (row, cond) => !cond || (cond.and ? cond.and.every((c) => match(row, c)) : row[cond.col] === cond.val);
      export const db = {
        insert: (t) => ({ values: (v) => ({ returning: async () => {
          if (v.url === "https://broken.example") throw new Error("price is not a number");
          const row = { id: t.__name + "-" + (++n), ...v }; globalThis.__rows[t.__name].push(row); return [row]; } }) }),
        select: () => ({ from: (t) => ({ where: (cond) => ({ limit: async () => globalThis.__rows[t.__name].filter((r) => match(r, cond)).slice(0, 1) }) }) }),
      };`,
    "./embedding-columns": "export const EMBEDDING_DIMENSIONS = 512;\nexport const embeddingColumnsFor = () => [];\n",
    "@/db/schema": `
      const col = (c) => ({ __col: c, columnType: 'PgText', dataType: 'string' });
      export const merchants = { __name: 'merchants', id: col('id'), domain: col('domain'), name: col('name') };
      export const merchantProducts = { __name: 'merchant_products', id: col('id'), merchantId: col('merchantId'), url: col('url'), title: col('title') };
      export const searchResults = { __name: 'search_results', id: col('id'), searchId: col('searchId'), merchantId: col('merchantId'), merchantProductId: col('merchantProductId'), matchScore: col('matchScore') };`,
    "drizzle-orm": "export const getTableName = (t) => t.__name; export const is = (v) => !!(v && v.__name); export class Table {}; export const eq = (c, v) => ({ col: c.__col, val: v }); export const and = (...c) => ({ and: c }); export const sql = () => ({});",
    "@/lib/error_reporter": "export const reportFromError = () => {};",
    "../fk-roles": "export const FK_ROLES = {}; export const fkRole = () => null; export const isDomainFk = () => false;",
    "@/lib/rules": "export const evaluateRuleSetForTable = async () => ({ errors: [], patches: {} });",
    "./engine": "globalThis.__handlers = {}; export const getActionHandler = (n) => globalThis.__handlers[n]; export const registerActionHandler = (n, h) => { globalThis.__handlers[n] = h; }; export const registerStepHandler = () => {}; export const executeWorkflow = async () => ({}); export const WorkflowEngine = class {}; export const getEngine = () => ({}); export const registerTriggerHandler = () => {}; export const runWorkflow = async () => ({});",
    "./ai": "export const registerAIActions = () => {};",
    "./ocr": "export const registerOcrActions = () => {};",
    "../events/emit-node": "export const makeEmitEventHandler = () => async () => ({});",
    "../feel-lite": "export const evaluateExpression = (e, v) => e === 'listing.price != null' ? v.listing?.price != null : null;",
    "./types": noop,
    fs: "export const promises = {}; export default { promises };",
    path: "export default { join: (...a) => a.join('/'), resolve: (...a) => a.join('/') }; export const join = (...a) => a.join('/');",
  },
});

const mod: any = await import("../workflows/index.ts");
mod.registerDefaultActions();
const h: any = (globalThis as any).__handlers;
ok(typeof h.for_each === "function", "the shipped module registers a for_each handler");

const rows = (globalThis as any).__rows;
const ctx: any = {
  user: { id: "u1" },
  variables: {
    create_search: { id: "search-1" },
    listing: "held before the loop",
    extract_listings: { output: [
      { domain: "nike.com", seller: "Nike", title: "Air Max 90", url: "https://nike.com/am90", matchScore: 0.97 },
      { domain: "nike.com", seller: "Nike", title: "Air Max 90 White", url: "https://nike.com/am90w", matchScore: 0.91 },
      { domain: "shop.example", seller: "Shop", title: "AM90 copy", url: "https://broken.example", matchScore: 0.2 },
    ] },
  },
};
const config = {
  actionType: "for_each", items: "{{extract_listings.output}}", as: "listing",
  steps: [
    { key: "merchant", config: { actionType: "db_insert", table: "merchants", findBy: ["domain"],
                                 values: { domain: "{{listing.domain}}", name: "{{listing.seller}}" } } },
    { key: "merchant_product", config: { actionType: "db_insert", table: "merchant_products",
                                         values: { merchantId: "{{merchant.id}}", url: "{{listing.url}}", title: "{{listing.title}}" } } },
    { key: "result", config: { actionType: "db_insert", table: "search_results",
                               values: { searchId: "{{create_search.id}}", merchantId: "{{merchant.id}}",
                                         merchantProductId: "{{merchant_product.id}}", matchScore: "{{listing.matchScore}}" } } },
  ],
};
const out = await h.for_each(config, ctx);

eqJson(rows.merchants.map((r: any) => r.domain), ["nike.com", "shop.example"], "one merchant per domain: found the second time, not created");
eqJson(rows.merchant_products.length, 2, "a merchant product per listing that could be saved");
eqJson(rows.search_results.map((r: any) => [r.searchId, r.merchantProductId]),
       [["search-1", rows.merchant_products[0].id], ["search-1", rows.merchant_products[1].id]],
       "each result points at the search and at its own merchant product");
ok(rows.merchant_products.every((p: any) => p.merchantId === rows.merchants[0].id), "and each product at the merchant found or made for it");
eqJson([out.count, out.done, out.failed], [3, 2, 1], "every item was tried; the one that failed is counted");
eqJson(out.errors[0].step, "merchant_product", "and says where it stopped");
eqJson(ctx.variables.listing, "held before the loop", "the loop's names are its own: what the workflow held comes back");
ok(!("merchant" in ctx.variables), "and an inner step's output does not leak past the loop");

const none = await h.for_each({ ...config, items: "{{nothing}}" }, { user: {}, variables: {} });
eqJson([none.count, none.failed], [0, 0], "no list is no work, never a crash");

rows.merchants.length = 0; rows.merchant_products.length = 0; rows.search_results.length = 0;
const priced: any = { user: {}, variables: { create_search: { id: "search-2" }, extract_listings: { output: [
  { domain: "a.example", seller: "A", title: "One", url: "https://a.example/1", matchScore: 0.9, price: 100 },
  { domain: "b.example", seller: "B", title: "Category page", url: "https://b.example/all", matchScore: 0.3, price: null },
] } } };
const kept = await h.for_each({ ...config, where: "listing.price != null" }, priced);
eqJson([kept.count, kept.skipped, kept.failed], [1, 1, 0], "an item the where rejects is skipped, not failed");
eqJson(rows.merchant_products.map((r: any) => r.url), ["https://a.example/1"], "and nothing of it is saved");

done("for_each carries each id forward");
