/** Send email action dispatcher. */

import { ActionDispatcher } from './base';

export class SendEmailDispatcher extends ActionDispatcher {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const to = this.resolver.resolveString((config.to as string) ?? '');
    const subject = this.resolver.resolveString((config.subject as string) ?? '');
    const template = this.resolver.resolveString((config.template as string) ?? '');
    const body = this.resolver.resolveString((config.body as string) ?? '');

    console.log(`[workflow] Email action — to: ${to}, subject: ${subject}`);

    return {
      action_type: 'send_email',
      to,
      subject,
      template,
      body,
      result: 'sent',
    };
  }
}
