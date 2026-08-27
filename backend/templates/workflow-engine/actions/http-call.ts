/** HTTP call action dispatcher — makes HTTP requests via fetch(). */

import { ActionDispatcher } from './base';

export class HttpCallDispatcher extends ActionDispatcher {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const url = this.resolver.resolveString((config.url as string) ?? '');
    const method = ((config.method as string) ?? 'GET').toUpperCase();
    const headers = this.resolver.resolveDict(
      (config.headers as Record<string, unknown>) ?? {},
    ) as Record<string, string>;
    const body = config.body
      ? this.resolver.resolveDict(config.body as Record<string, unknown>)
      : undefined;

    console.log(`[workflow] HTTP ${method} ${url}`);

    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', ...headers },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(30_000),
    });

    let responseBody: unknown;
    try {
      responseBody = await response.json();
    } catch {
      const text = await response.text();
      responseBody = text.slice(0, 2000);
    }

    return {
      action_type: 'http_call',
      status_code: response.status,
      response: responseBody,
      result: response.ok ? 'success' : 'error',
    };
  }
}
