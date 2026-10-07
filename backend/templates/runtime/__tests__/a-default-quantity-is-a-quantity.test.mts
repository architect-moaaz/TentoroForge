/**
 * `{{quantity ?? 1}}` in a set_variable step is the quantity, or 1. The
 * engine's own resolver read it as one variable named "quantity ?? 1", stored
 * null, and ToroCommerce's Add to Cart compared null with the stock and
 * refused every shopper "There isn't enough stock" (forge-v3, 2026-10-07).
 *
 * Runs the SHIPPED engine.ts with the real expression evaluator.
 */
import { installHarness, eqJson, done } from "./_harness.mts";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
installHarness({ stubs: { "./types": "export default {};" },
                 redirect: { "../feel-lite": join(HERE, "..", "feel-lite", "index.ts") } });

const engine: any = await import("../workflows/engine.ts");
const iv = engine.interpolateValue;

console.log("fallbacks in a template");
eqJson(iv("{{quantity ?? 1}}", { quantity: 2 }), 2, "a quantity given is kept");
eqJson(iv("{{quantity ?? 1}}", {}), 1, "none given takes the number after ??");
eqJson(iv("{{note ?? \"none\"}}", { note: "" }), "none", "empty text is nothing; the next side is tried");
eqJson(iv("{{a ?? b ?? 'x'}}", { b: "B" }), "B", "the first side that holds something");
eqJson(iv("{{flag ?? false}}", {}), false, "a literal false");
eqJson(iv("Added {{quantity ?? 1}} item(s)", {}), "Added 1 item(s)", "inside text too");
eqJson(iv("{{variant.stock}}", { variant: { stock: 3 } }), 3, "a plain path reads as before");
eqJson(iv("{{missing}}", {}), null, "and an unresolved one is still null, never its spelling");

console.log("ToroCommerce's Add to Cart, as written");
const handled: string[] = [];
engine.registerActionHandler("db_insert", async () => { handled.push("insert"); return { id: "ci-1" }; });
const workflow = { id: "add-to-cart", name: "Add to Cart", definition: {
  trigger: { type: "manual" },
  nodes: [
    { id: "trigger", type: "trigger", data: { label: "Start", config: {} } },
    { id: "set_addqty", type: "action", data: { label: "Quantity", config: { actionType: "set_variable", variableName: "addQty", value: "{{quantity ?? 1}}" } } },
    { id: "check_stock", type: "condition", data: { label: "In stock?", config: { expression: "addQty <= variant.stock" } } },
    { id: "insert_new", type: "action", data: { label: "Add line", config: { actionType: "db_insert" } } },
    { id: "insufficient", type: "end", data: { label: "No stock", config: { refused: true, message: "There isn't enough stock" } } },
    { id: "end_success", type: "end", data: { label: "Added", config: {} } },
  ],
  edges: [
    { id: "e1", source: "trigger", target: "set_addqty" },
    { id: "e2", source: "set_addqty", target: "check_stock" },
    { id: "e3", source: "check_stock", target: "insert_new", data: { edgeType: "then" } },
    { id: "e4", source: "check_stock", target: "insufficient", sourceHandle: "else", data: { edgeType: "else" } },
    { id: "e5", source: "insert_new", target: "end_success" },
  ],
} };
const ran: any = await engine.executeWorkflow(workflow, { variant: { id: "v1", stock: 3 } }, { id: "c-1" });
eqJson([ran.status, handled], ["completed", ["insert"]], "a shopper with no quantity adds one item that is in stock");
const over: any = await engine.executeWorkflow(workflow, { variant: { id: "v1", stock: 3 }, quantity: 5 }, { id: "c-1" });
eqJson(over.status === "completed" ? "added" : "refused", "refused", "and more than the stock is still refused");
done("default-quantity");
