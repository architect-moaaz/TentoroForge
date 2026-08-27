/**
 * Task Detail (Slice E T2) — one pending workflow task, with a
 * decision form the assignee submits to resume the workflow.
 *
 * Fetches /api/tasks/[id] (shipped alongside — see the api-tasks
 * template) then renders the task's process_variables as read-only
 * context and shows Approve / Reject buttons. Submission POSTs to
 * /api/workflows/[workflowId]/execute with `{ taskId, input: {
 * __decision, comment } }` — the existing execute route already
 * treats a POST-with-taskId as a resume (see runtime_injector.py
 * _generate_workflow_api_route, "Row-level Approve/Reject" branch).
 *
 * Renders as a Client Component because the form needs local state
 * for the comment field and the disabled-while-submitting affordance.
 * Ships via services.runtime_injector._inject_task_inbox_pages.
 */
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

type TaskRow = {
  id: string;
  workflow_id: string;
  node_id: string | null;
  node_label: string | null;
  status: string;
  entity_type: string | null;
  entity_id: string | null;
  process_variables: Record<string, unknown> | null;
  form_binding: Record<string, unknown> | null;
  created_at: string | null;
};

export default function TaskDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [task, setTask] = useState<TaskRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params?.id) return;
    (async () => {
      try {
        const res = await fetch(`/api/tasks/${params.id}`, { cache: "no-store" });
        if (!res.ok) throw new Error(await res.text());
        setTask(await res.json());
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    })();
  }, [params?.id]);

  async function submit(decision: "approve" | "reject") {
    if (!task) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/workflows/${task.workflow_id}/execute`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            taskId: task.id,
            input: {
              __decision: decision,
              comment,
              entityId: task.entity_id,
              entityType: task.entity_type,
            },
          }),
        },
      );
      if (!res.ok) throw new Error(await res.text());
      router.push("/tasks");
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  }

  if (loading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }
  if (!task) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <div className="rounded-md border border-border p-6 text-center text-muted-foreground">
          {error || "Task not found."}
        </div>
        <div className="mt-4">
          <Link href="/tasks" className="text-sm underline">
            ← Back to Tasks
          </Link>
        </div>
      </div>
    );
  }

  const vars = task.process_variables ?? {};
  const varEntries = Object.entries(vars);

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <Link href="/tasks" className="text-sm text-muted-foreground underline">
        ← Back to Tasks
      </Link>
      <h1 className="mt-3 text-2xl font-semibold">
        {task.node_label || "Review this item"}
      </h1>
      <p className="text-sm text-muted-foreground">
        {task.entity_type && task.entity_id
          ? `${task.entity_type} ${task.entity_id}`
          : `Workflow ${task.workflow_id}`}
      </p>

      {varEntries.length > 0 ? (
        <dl className="mt-6 rounded-md border border-border p-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
          {varEntries.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="font-medium text-foreground break-words">
                {typeof v === "string" || typeof v === "number" || typeof v === "boolean"
                  ? String(v)
                  : JSON.stringify(v)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <div className="mt-6">
        <label className="block text-sm font-medium mb-1" htmlFor="comment">
          Comment (optional)
        </label>
        <textarea
          id="comment"
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={submitting}
          className="w-full rounded-md border border-border px-3 py-2 text-sm bg-background"
        />
      </div>

      {error ? (
        <div className="mt-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="mt-6 flex gap-3">
        <button
          type="button"
          disabled={submitting}
          onClick={() => submit("approve")}
          className="rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {submitting ? "Working…" : "Approve"}
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={() => submit("reject")}
          className="rounded-md border border-border px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
