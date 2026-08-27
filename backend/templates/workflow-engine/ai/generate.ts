/** AI generate handler — generates text content. */

import { AINodeHandler } from './base';

export class GenerateHandler extends AINodeHandler {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const aiPrompt = this.resolver.resolveString((config.aiPrompt as string) ?? '');
    const aiTone = (config.aiTone as string) ?? 'professional';
    const aiInput = this.resolver.resolveString((config.aiInput as string) ?? '');

    const systemPrompt =
      `You are a content generation assistant. Write in a ${aiTone} tone. ` +
      'Respond with JSON: {"generated_text": "<your generated content>"}';

    let userPrompt = aiPrompt;
    if (aiInput) {
      userPrompt = aiPrompt ? `${aiPrompt}\n\nContext:\n${aiInput}` : aiInput;
    }

    const response = await this.callLLM(systemPrompt, userPrompt || 'Generate content.');
    const parsed = this.parseJsonResponse(response);

    const generatedText = (parsed.generated_text as string) ?? (parsed.raw_response as string) ?? '';

    return {
      generated_text: generatedText,
      tone: aiTone,
      output: generatedText,
    };
  }

  protected override mockResponse(): string {
    return JSON.stringify({
      generated_text: 'This is mock-generated content for testing purposes.',
    });
  }
}
