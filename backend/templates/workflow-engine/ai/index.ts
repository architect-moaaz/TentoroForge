/** AI handler registry and factory. */

import type { AINodeHandler } from './base';
import { ClassifyHandler } from './classify';
import { ExtractHandler } from './extract';
import { DecideHandler } from './decide';
import { GenerateHandler } from './generate';

type HandlerClass = new (variables: Record<string, unknown>) => AINodeHandler;

const AI_HANDLERS: Record<string, HandlerClass> = {
  ai_classify: ClassifyHandler,
  ai_extract: ExtractHandler,
  ai_decide: DecideHandler,
  ai_generate: GenerateHandler,
};

export function getAiHandler(
  nodeType: string,
  variables: Record<string, unknown>,
): AINodeHandler {
  const Cls = AI_HANDLERS[nodeType];
  if (!Cls) throw new Error(`Unknown AI node type: ${nodeType}`);
  return new Cls(variables);
}

export { AINodeHandler } from './base';
