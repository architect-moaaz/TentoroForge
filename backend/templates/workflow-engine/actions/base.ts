/** Base action dispatcher for workflow service tasks. */

import { VariableResolver } from '../domain/variable-resolver';

export abstract class ActionDispatcher {
  protected resolver: VariableResolver;

  constructor(protected variables: Record<string, unknown>) {
    this.resolver = new VariableResolver(variables);
  }

  abstract execute(config: Record<string, unknown>): Promise<Record<string, unknown>>;
}
