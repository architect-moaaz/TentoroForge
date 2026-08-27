/** DB query action dispatcher — dynamic Drizzle table query via schema[model]. */

import { eq, gt, lt, gte, lte, sql } from 'drizzle-orm';
import { db } from '@/db';
import { ActionDispatcher } from './base';

export class DbQueryDispatcher extends ActionDispatcher {
  async execute(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    const model = this.resolver.resolveString((config.model as string) ?? '');
    const operation = (config.operation as string) ?? 'select';
    const description = this.resolver.resolveString((config.description as string) ?? '');

    if (!model) {
      return { action_type: 'db_query', result: 'error', error: 'No model specified' };
    }

    console.log(`[workflow] DB query — model: ${model}, operation: ${operation}`);

    try {
      // Dynamic import of the app's schema
      const schema = await import('@/db/schema');
      const table = (schema as Record<string, unknown>)[model];

      if (!table) {
        return {
          action_type: 'db_query',
          model,
          result: 'error',
          error: `Table "${model}" not found in schema`,
        };
      }

      const whereConfig = config.where
        ? this.resolver.resolveDict(config.where as Record<string, unknown>)
        : {};
      const dataConfig = config.data
        ? this.resolver.resolveDict(config.data as Record<string, unknown>)
        : {};

      let result: unknown;

      switch (operation) {
        case 'select': {
          let query = db.select().from(table as any);
          query = this.applyWhere(query, table, whereConfig) as any;
          result = await query;
          break;
        }
        case 'insert': {
          result = await db.insert(table as any).values(dataConfig).returning();
          break;
        }
        case 'update': {
          let query = db.update(table as any).set(dataConfig);
          query = this.applyWhere(query, table, whereConfig) as any;
          result = await (query as any).returning();
          break;
        }
        case 'count': {
          let query = db.select({ count: sql<number>`count(*)` }).from(table as any);
          query = this.applyWhere(query, table, whereConfig) as any;
          const rows = await query;
          result = rows[0]?.count ?? 0;
          break;
        }
        default:
          return { action_type: 'db_query', result: 'error', error: `Unknown operation: ${operation}` };
      }

      return {
        action_type: 'db_query',
        model,
        operation,
        description,
        data: result,
        result: 'success',
      };
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      console.error(`[workflow] DB query failed: ${msg}`);
      return { action_type: 'db_query', model, result: 'error', error: msg };
    }
  }

  private applyWhere(query: any, table: any, whereConfig: Record<string, unknown>): any {
    for (const [key, value] of Object.entries(whereConfig)) {
      if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
        const op = value as Record<string, unknown>;
        const column = table[key];
        if (!column) continue;
        if ('gt' in op) query = query.where(gt(column, op.gt));
        if ('lt' in op) query = query.where(lt(column, op.lt));
        if ('gte' in op) query = query.where(gte(column, op.gte));
        if ('lte' in op) query = query.where(lte(column, op.lte));
        if ('eq' in op) query = query.where(eq(column, op.eq));
      } else if (table[key]) {
        query = query.where(eq(table[key], value));
      }
    }
    return query;
  }
}
