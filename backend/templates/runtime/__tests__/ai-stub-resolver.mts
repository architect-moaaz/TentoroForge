/**
 * Test stub for `@/lib/integrations/resolver` (used only by
 * ai-identify-product.test.mts via esbuild --alias). Returns whatever
 * the test placed on globalThis.__forgeStubApiKey (default: a dummy key
 * so callLLM proceeds past the no-key branch and reaches the mocked SDK).
 */
export async function getSecret(_provider: string, key: string): Promise<string> {
  if (key === "ANTHROPIC_API_KEY") {
    const stub = (globalThis as any).__forgeStubApiKey;
    return stub === undefined ? "sk-test-key" : String(stub ?? "");
  }
  if (key === "FORGE_AI_MODEL") return "claude-sonnet-4-6";
  return "";
}
