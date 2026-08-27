/** AI classify handler — classifies input into labels. */

import { AINodeHandler } from './base';

export class ClassifyHandler extends AINodeHandler {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const aiInput = this.resolver.resolveString((config.aiInput as string) ?? '');
    const aiLabels = (config.aiLabels as string[]) ?? [];
    const aiPrompt = this.resolver.resolveString((config.aiPrompt as string) ?? '');
    const threshold = parseFloat(String(config.aiThreshold ?? 0.7));

    const labelsStr = aiLabels.length > 0 ? aiLabels.join(', ') : 'positive, negative, neutral';

    const systemPrompt =
      'You are a classification assistant. Classify the input into exactly one of the ' +
      `given labels. Labels: [${labelsStr}]. ` +
      'Respond with JSON: {"label": "<label>", "confidence": <0.0-1.0>}';
    const userPrompt = aiPrompt ? `${aiPrompt}\n\nInput to classify:\n${aiInput}` : aiInput;

    const response = await this.callLLM(systemPrompt, userPrompt);
    const parsed = this.parseJsonResponse(response);

    const label = (parsed.label as string) ?? (aiLabels[0] ?? 'unknown');
    const confidence = parseFloat(String(parsed.confidence ?? 0.8));

    return {
      label,
      confidence,
      meets_threshold: confidence >= threshold,
      output: label,
    };
  }

  protected override mockResponse(): string {
    return JSON.stringify({ label: 'positive', confidence: 0.85 });
  }
}
