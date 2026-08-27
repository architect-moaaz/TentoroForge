/** Variable resolver — resolves {{path.to.value}} templates in workflow data. */

const TEMPLATE_RE = /\{\{(.+?)\}\}/g;
const SENTINEL = Symbol('unresolvable');

export class VariableResolver {
  constructor(private variables: Record<string, unknown>) {}

  /** Replace all {{path}} occurrences in a string with resolved values. */
  resolveString(template: string): string {
    if (!template.includes('{{')) return template;
    return template.replace(TEMPLATE_RE, (match, path: string) => {
      const value = this.resolvePath(path.trim());
      if (value === SENTINEL) return match;
      return typeof value === 'string' ? value : String(value);
    });
  }

  /** Recursively resolve all string values in an object. */
  resolveDict(data: Record<string, unknown>): Record<string, unknown> {
    const resolved: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(data)) {
      resolved[key] = this.resolveValue(value);
    }
    return resolved;
  }

  /** Resolve a single value (string, object, array, or passthrough). */
  resolveValue(value: unknown): unknown {
    if (typeof value === 'string') return this.resolveString(value);
    if (Array.isArray(value)) return value.map((item) => this.resolveValue(item));
    if (value !== null && typeof value === 'object') {
      return this.resolveDict(value as Record<string, unknown>);
    }
    return value;
  }

  /** Walk dot-separated path in variables dict. Returns SENTINEL if unresolvable. */
  private resolvePath(path: string): unknown {
    const parts = path.split('.');
    let current: unknown = this.variables;
    for (const part of parts) {
      if (current !== null && typeof current === 'object' && part in (current as Record<string, unknown>)) {
        current = (current as Record<string, unknown>)[part];
      } else {
        return SENTINEL;
      }
    }
    return current;
  }
}
