/** AI decide handler — makes boolean decision for then/else branching. */

import { AINodeHandler } from './base';

export class DecideHandler extends AINodeHandler {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const aiContext = this.resolver.resolveString((config.aiContext as string) ?? '');
    const aiOptions = (config.aiOptions as string[]) ?? [];
    const aiRules = this.resolver.resolveString((config.aiRules as string) ?? '');
    const aiPrompt = this.resolver.resolveString((config.aiPrompt as string) ?? '');

    const optionsStr = aiOptions.length > 0 ? aiOptions.join(', ') : 'approve, reject';

    const systemPrompt =
      'You are a decision-making assistant. Based on the context and rules provided, ' +
      `make a decision. Options: [${optionsStr}]. ` +
      'Respond with JSON: {"decision": true/false, "confidence": <0.0-1.0>, "reasoning": "<brief explanation>"}\n' +
      'decision=true means the primary/positive option, false means the secondary/negative option.';

    const contextParts: string[] = [];
    if (aiContext) contextParts.push(`Context: ${aiContext}`);
    if (aiRules) contextParts.push(`Rules: ${aiRules}`);
    if (aiPrompt) contextParts.push(`Additional instructions: ${aiPrompt}`);
    const userPrompt = contextParts.length > 0
      ? contextParts.join('\n\n')
      : 'Make a decision based on available information.';

    const response = await this.callLLM(systemPrompt, userPrompt);
    const parsed = this.parseJsonResponse(response);

    const decision = Boolean(parsed.decision ?? true);
    const confidence = parseFloat(String(parsed.confidence ?? 0.8));
    const reasoning = (parsed.reasoning as string) ?? '';

    return {
      decision,
      confidence,
      reasoning,
      output: decision,
    };
  }

  protected override mockResponse(): string {
    return JSON.stringify({
      decision: true,
      confidence: 0.85,
      reasoning: 'Mock decision — defaulting to true',
    });
  }
}
