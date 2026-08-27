/** AI extract handler — extracts structured fields from input. */

import { AINodeHandler } from './base';

export class ExtractHandler extends AINodeHandler {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const aiInput = this.resolver.resolveString((config.aiInput as string) ?? '');
    const aiFields = (config.aiExtractFields as string[]) ?? [];
    const aiPrompt = this.resolver.resolveString((config.aiPrompt as string) ?? '');

    const fieldsStr = aiFields.length > 0 ? aiFields.join(', ') : 'name, email, phone';

    const systemPrompt =
      'You are a data extraction assistant. Extract the following fields from the input: ' +
      `[${fieldsStr}]. ` +
      'Respond with JSON containing the extracted fields. Use null for fields not found.';
    const userPrompt = aiPrompt ? `${aiPrompt}\n\nInput:\n${aiInput}` : aiInput;

    const response = await this.callLLM(systemPrompt, userPrompt);
    const parsed = this.parseJsonResponse(response);

    return {
      extracted_fields: parsed,
      output: parsed,
    };
  }

  protected override mockResponse(): string {
    return JSON.stringify({ name: 'Mock User', email: 'mock@example.com' });
  }
}
