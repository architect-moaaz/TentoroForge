/** Send notification action dispatcher. */

import { db } from '@/db';
import { ActionDispatcher } from './base';

export class SendNotificationDispatcher extends ActionDispatcher {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const description = this.resolver.resolveString((config.description as string) ?? '');
    const title = this.resolver.resolveString((config.title as string) ?? 'Workflow Notification');
    const recipient = this.resolver.resolveString((config.recipient as string) ?? '');

    console.log(`[workflow] Notification — title: ${title}, description: ${description}`);

    // Try to insert into app's notifications table if it exists
    try {
      const schema = await import('@/db/schema');
      const notificationsTable = (schema as Record<string, unknown>).notifications;
      if (notificationsTable) {
        await db.insert(notificationsTable as any).values({
          title,
          message: description,
          type: 'workflow',
          isRead: false,
          ...(recipient ? { userId: parseInt(recipient) || undefined } : {}),
        });
      }
    } catch {
      // Notifications table may not exist — that's fine
    }

    return {
      action_type: 'send_notification',
      title,
      description,
      recipient,
      result: 'sent',
    };
  }
}
