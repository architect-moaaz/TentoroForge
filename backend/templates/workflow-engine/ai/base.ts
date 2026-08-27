/** Base AI node handler with LLM call + mock fallback. */

import { VariableResolver } from '../domain/variable-resolver';

export abstract class AINodeHandler {
  protected resolver: VariableResolver;

  constructor(protected variables: Record<string, unknown>) {
    this.resolver = new VariableResolver(variables);
  }

  abstract execute(config: Record<string, unknown>): Promise<Record<string, unknown>>;

  /** Call the Anthropic Claude API. Falls back to mock if no API key. */
  protected async callLLM(systemPrompt: string, userPrompt: string): Promise<string> {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      console.log('[workflow] No ANTHROPIC_API_KEY — using mock response');
      return this.mockResponse(systemPrompt, userPrompt);
    }

    try {
      const { default: Anthropic } = await import('@anthropic-ai/sdk');
      const client = new Anthropic({ apiKey });
      const message = await client.messages.create({
        model: 'claude-sonnet-4-6',
        max_tokens: 1024,
        system: systemPrompt,
        messages: [{ role: 'user', content: userPrompt }],
      });
      const block = message.content[0];
      return block.type === 'text' ? block.text : JSON.stringify(block);
    } catch (error) {
      console.warn('[workflow] LLM call failed, using mock:', error);
      return this.mockResponse(systemPrompt, userPrompt);
    }
  }

  /** Deterministic mock response for dev/test environments. */
  protected mockResponse(_systemPrompt: string, _userPrompt: string): string {
    return JSON.stringify({ mock: true, result: 'mock_response' });
  }

  /** Try to parse JSON from LLM response, handling markdown code blocks. */
  protected parseJsonResponse(text: string): Record<string, unknown> {
    text = text.trim();
    if (text.startsWith('```')) {
      const lines = text.split('\n').filter((l) => !l.trim().startsWith('```'));
      text = lines.join('\n').trim();
    }
    try {
      return JSON.parse(text);
    } catch {
      return { raw_response: text };
    }
  }
}
