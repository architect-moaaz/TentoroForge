/**
 * Test stub for `@anthropic-ai/sdk` (used only by
 * ai-identify-product.test.mts via esbuild --alias). Simulates the
 * `client.messages.create` contract: returns a single text block whose
 * text is whatever the test placed on globalThis.__forgeStubResponse.
 */
export class Anthropic {
  constructor(_opts: { apiKey: string }) {}
  messages = {
    create: async (_req: any) => {
      const text = (globalThis as any).__forgeStubResponse ?? "";
      return { content: [{ type: "text", text }] };
    },
  };
}
export default Anthropic;
