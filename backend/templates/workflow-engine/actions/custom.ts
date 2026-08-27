/** Custom action dispatcher — generic placeholder for user-defined actions. */

import { ActionDispatcher } from './base';

export class CustomActionDispatcher extends ActionDispatcher {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const description = this.resolver.resolveString(
      (config.description as string) ?? 'Custom action',
    );
    console.log('[workflow] Custom action executed:', description);
    return {
      action_type: 'custom',
      description,
      result: 'success',
    };
  }
}
