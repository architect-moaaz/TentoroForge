/**
 * Saved Views — persist and retrieve user-defined filter/sort presets per table.
 *
 * Generated apps call these helpers from their API routes for saved-view CRUD.
 * Uses `db: any` — adapt insert/select/delete calls to your ORM.
 *
 * Routes (suggested):
 *   GET    /api/data/{table}/views       → listSavedViews
 *   POST   /api/data/{table}/views       → createSavedView
 *   DELETE /api/data/{table}/views/{id}  → deleteSavedView
 */

export interface SavedView {
  id: string;
  userId: string;
  table: string;          // which entity this view is for
  label: string;
  filters: Record<string, any>;
  sortBy?: { field: string; direction: "asc" | "desc" };
  createdAt: string;
}

const SAVED_VIEWS_TABLE = "saved_views";

/**
 * List all saved views for a user + table combination.
 */
export async function listSavedViews(
  db: any,
  userId: string,
  table: string,
): Promise<SavedView[]> {
  return db.select().from(SAVED_VIEWS_TABLE).where({ userId, table });
}

/**
 * Create a new saved view. Generates a UUID id and timestamps it.
 */
export async function createSavedView(
  db: any,
  view: Omit<SavedView, "id" | "createdAt">,
): Promise<SavedView> {
  const full: SavedView = {
    ...view,
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
  };
  await db.insert(SAVED_VIEWS_TABLE).values(full);
  return full;
}

/**
 * Delete a saved view. Requires both id and userId to prevent
 * users from deleting each other's views.
 */
export async function deleteSavedView(
  db: any,
  id: string,
  userId: string,
): Promise<void> {
  await db.delete().from(SAVED_VIEWS_TABLE).where({ id, userId });
}
