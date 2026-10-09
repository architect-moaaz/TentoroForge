/**
 * `a ?? b` in a formula: a's value, or else b's.
 *
 * Process authors write it as they would in any language; the formula parser
 * refused it, and ToroCommerce's Place Order lost its unit-price step to the
 * refusal (torob2, 2026-10-09). Runs the SHIPPED feel-lite.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();   // feel-lite imports its siblings without extensions
const { evaluateExpression } = await import("../feel-lite/index.ts");

const variant = { priceOverride: null };
const product = { basePrice: 40 };
eqJson(evaluateExpression("variant.priceOverride ?? product.basePrice", { variant, product }), 40,
       "an empty override falls back to the product's price");
eqJson(evaluateExpression("variant.priceOverride ?? product.basePrice", { variant: { priceOverride: 25 }, product }), 25,
       "a set override wins");
eqJson(evaluateExpression("variant.priceOverride ?? product.basePrice * 2", { variant, product }), 80,
       "?? is looser than arithmetic: the fallback is the whole right side");
eqJson(evaluateExpression('note ?? "none"', { note: "" }), "none", "a field never filled reads as empty");
eqJson(evaluateExpression("count ?? 1", { count: 0 }), 0, "zero is a value, not an absence");
ok(evaluateExpression("a ?? b ?? 3", {}) === 3, "it chains");
done();
