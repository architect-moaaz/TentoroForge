/**
 * Standalone test for the `ai_identify_product` vision preset handler
 * (workflows/ai.ts). Covers the contract:
 *
 *   in  → { image_file_id: <forge_files id> } (or aiFileRef / aiInput)
 *   out → { brand, model, category, attributes, confidence? } — strict JSON,
 *         extracted-fields promoted onto process variables
 *
 * ai.ts's `callLLM` reaches Anthropic via a dynamic import of
 * `@anthropic-ai/sdk` (SDK not installed here) and reads the API key via a
 * dynamic import of `@/lib/integrations/resolver`. run-identify-tests.sh
 * bundles this file with esbuild + `--alias` so both modules resolve to
 * the tiny stubs in this directory (see ai-stub-resolver.mts /
 * ai-stub-anthropic.mts). The stub SDK returns whatever JSON the test
 * puts on `globalThis.__forgeStubResponse`, so we can drive the whole
 * handler end-to-end without a real Claude call.
 *
 * Run: __tests__/run-identify-tests.sh
 * Exits 0 on pass, 1 on any failure.
 */
import { aiIdentifyProduct, setFileLoader } from "../workflows/ai.ts";

// ── tiny harness ────────────────────────────────────────────────────────
let passed = 0;
let failed = 0;
function assertEq<T>(actual: T, expected: T, name: string): void {
  const ok =
    actual === expected ||
    JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`      expected: ${JSON.stringify(expected)}`);
    console.log(`      actual:   ${JSON.stringify(actual)}`);
  }
}
async function assertThrows(
  fn: () => Promise<unknown>,
  match: RegExp,
  name: string,
): Promise<void> {
  try {
    await fn();
    failed++;
    console.log(`  ✗ ${name}  — did not throw`);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (match.test(msg)) {
      passed++;
      console.log(`  ✓ ${name}`);
    } else {
      failed++;
      console.log(`  ✗ ${name}`);
      console.log(`      expected match: ${match}`);
      console.log(`      actual message: ${msg}`);
    }
  }
}

// ── fixtures ────────────────────────────────────────────────────────────
// Register a fake file loader so loadDocs(id) returns a base64 image.
setFileLoader(async (ref: string) => {
  if (ref === "img-1") {
    return {
      base64: "iVBORw0KGgo=",
      mediaType: "image/png",
      filename: "shoe.png",
    };
  }
  if (ref === "pdf-1") {
    return {
      base64: "JVBERi0=",
      mediaType: "application/pdf",
      filename: "spec.pdf",
    };
  }
  return null;
});

function ctx() {
  return { variables: {} as Record<string, unknown> };
}

// ── tests ───────────────────────────────────────────────────────────────

console.log("ai_identify_product — missing image_file_id throws:");
await assertThrows(
  () => aiIdentifyProduct({ actionType: "ai_identify_product" } as any, ctx() as any),
  /image_file_id is required/,
  "missing image ref rejected",
);

console.log("ai_identify_product — non-image mime rejected:");
await assertThrows(
  () =>
    aiIdentifyProduct(
      { actionType: "ai_identify_product", image_file_id: "pdf-1" } as any,
      ctx() as any,
    ),
  /could not load an image/,
  "pdf file rejected (image required)",
);

console.log("ai_identify_product — happy path (mocked SDK response):");
{
  (globalThis as any).__forgeStubResponse = JSON.stringify({
    brand: "Nike",
    model: "Air Max 90",
    category: "sneakers",
    attributes: { color: "white", size: "10" },
    confidence: 0.92,
  });
  const c = ctx();
  const out = await aiIdentifyProduct(
    { actionType: "ai_identify_product", image_file_id: "img-1" } as any,
    c as any,
  );
  assertEq(out.brand, "Nike", "brand");
  assertEq(out.model, "Air Max 90", "model");
  assertEq(out.category, "sneakers", "category");
  assertEq((out.attributes as any).color, "white", "attributes.color");
  assertEq(out.confidence, 0.92, "confidence");
  // Extracted fields promoted to process vars.
  assertEq(c.variables.brand, "Nike", "brand promoted to process vars");
  assertEq(c.variables.category, "sneakers", "category promoted to process vars");
}

console.log("ai_identify_product — JSON-in-fence still parses:");
{
  (globalThis as any).__forgeStubResponse =
    "```json\n{\"brand\":\"Sony\",\"model\":\"WH-1000XM5\",\"category\":\"headphones\",\"attributes\":{}}\n```";
  const out = await aiIdentifyProduct(
    { actionType: "ai_identify_product", image_file_id: "img-1" } as any,
    ctx() as any,
  );
  assertEq(out.brand, "Sony", "brand from fenced JSON");
  assertEq(out.model, "WH-1000XM5", "model from fenced JSON");
}

console.log("ai_identify_product — malformed model output throws:");
{
  (globalThis as any).__forgeStubResponse = "sorry, I can't see the image";
  await assertThrows(
    () =>
      aiIdentifyProduct(
        { actionType: "ai_identify_product", image_file_id: "img-1" } as any,
        ctx() as any,
      ),
    /not a JSON object/,
    "prose response rejected",
  );
}

console.log("ai_identify_product — aiFileRef alias still accepted:");
{
  (globalThis as any).__forgeStubResponse = JSON.stringify({
    brand: "Levi's",
    model: "501",
    category: "jeans",
    attributes: { color: "blue" },
  });
  const out = await aiIdentifyProduct(
    { actionType: "ai_identify_product", aiFileRef: "img-1" } as any,
    ctx() as any,
  );
  assertEq(out.brand, "Levi's", "brand via aiFileRef");
  assertEq(out.category, "jeans", "category via aiFileRef");
  // confidence omitted → not present in output
  assertEq("confidence" in (out as any), false, "confidence absent when unset");
}

console.log("ai_identify_product — no API key surfaces a clear error:");
{
  (globalThis as any).__forgeStubApiKey = ""; // opt out for this test
  (globalThis as any).__forgeStubResponse = JSON.stringify({ brand: "x" });
  await assertThrows(
    () =>
      aiIdentifyProduct(
        { actionType: "ai_identify_product", image_file_id: "img-1" } as any,
        ctx() as any,
      ),
    /no model response|Configure ANTHROPIC_API_KEY|not a JSON object/,
    "missing key path errors cleanly",
  );
  (globalThis as any).__forgeStubApiKey = undefined;
}

// ── report ──────────────────────────────────────────────────────────────
console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
