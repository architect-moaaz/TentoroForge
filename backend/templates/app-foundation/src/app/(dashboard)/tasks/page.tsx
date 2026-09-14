/**
 * Task Inbox (Slice E T2) — every logged-in user's queue of pending
 * human tasks emitted by workflow user_task / approval nodes.
 *
 * Server Component. Fetches /api/tasks?status=pending (existing
 * runtime-shipped route) with the current cookie, then renders a
 * plain, keyboard-navigable list. No Suspense, no client-only state —
 * a task row is a link to /tasks/[id], nothing more.
 *
 * When there are no pending tasks the page still renders — an empty
 * inbox is a meaningful state, not an error.
 *
 * Ships via services.runtime_injector._inject_task_inbox_pages.
 */
import Link from "next/link";
import { cookies, headers } from "next/headers";

export const dynamic = "force-dynamic";

type TaskRow = {
  id: string;
  node_label?: string | null;
  workflow_id?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  status?: string | null;
  created_at?: string | null;
  due_at?: string | null;
};

async function fetchTasks(): Promise<TaskRow[]> {
  // Forward the current cookie so the /api/tasks auth check sees the
  // same session the page was rendered under.
  const cookieHeader = (await cookies())
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const host = (await headers()).get("host") || "localhost:3000";
  const proto = (await headers()).get("x-forwarded-proto") || "http";
  try {
    const res = await fetch(`${proto}://${host}/api/tasks?status=pending`, {
      headers: { cookie: cookieHeader },
      cache: "no-store",
    });
    if (!res.ok) return [];
    const rows = await res.json();
    return Array.isArray(rows) ? (rows as TaskRow[]) : [];
  } catch {
    return [];
  }
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return "";
  }
}

export default async function TasksPage() {
  const tasks = await fetchTasks();

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold mb-1">Tasks</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Pending items waiting for your review.
      </p>

      {tasks.length === 0 ? (
        <div className="rounded-md border border-border p-8 text-center text-muted-foreground">
          Nothing to do — your inbox is clear.
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {tasks.map((t) => (
            <li key={t.id} className="hover:bg-muted/40">
              <Link
                href={`/tasks/${t.id}`}
                className="block p-4 focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <div className="flex items-baseline justify-between gap-4">
                  <div className="font-medium text-foreground">
                    {t.node_label || "Task"}
                  </div>
                  <div className="text-xs text-muted-foreground shrink-0">
                    {formatWhen(t.created_at)}
                  </div>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {t.workflow_id ? `Workflow: ${t.workflow_id}` : null}
                  {t.entity_id ? ` · ${t.entity_type || "item"} ${t.entity_id}` : null}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
