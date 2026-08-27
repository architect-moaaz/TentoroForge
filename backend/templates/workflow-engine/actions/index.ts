/** Action dispatcher registry and factory. */

import type { ActionDispatcher } from './base';
import { CustomActionDispatcher } from './custom';
import { HttpCallDispatcher } from './http-call';
import { DbQueryDispatcher } from './db-query';
import { SendEmailDispatcher } from './send-email';
import { SendNotificationDispatcher } from './send-notification';

type DispatcherClass = new (variables: Record<string, unknown>) => ActionDispatcher;

const ACTION_DISPATCHERS: Record<string, DispatcherClass> = {
  custom: CustomActionDispatcher,
  http_call: HttpCallDispatcher,
  api_call: HttpCallDispatcher,
  db_query: DbQueryDispatcher,
  send_email: SendEmailDispatcher,
  send_notification: SendNotificationDispatcher,
};

export function getDispatcher(
  actionType: string,
  variables: Record<string, unknown>,
): ActionDispatcher {
  const Cls = ACTION_DISPATCHERS[actionType] ?? CustomActionDispatcher;
  return new Cls(variables);
}

export { ActionDispatcher } from './base';
