// PLACEHOLDER of the generated `src/sdk/pages.ts` — not copied into apps. The
// real one is `emit_pages` in services/blueprint/app_sdk.py (identical to the
// web app's): one handle per page and `href` to build its address.

/** A page of this application. `R` is its route; `[param]` segments are
 *  what `href` must be given. */
export interface PageRef<R extends string = string> {
  id: string;
  name: string;
  route: R;
}

type Params<R extends string> = R extends `${string}[${infer P}]${infer Rest}`
  ? { [K in P | keyof Params<Rest>]: string } : {};

/** The URL of a page: `href(pages.taskDetail, { id: row.id })`. */
export function href<R extends string>(
  page: PageRef<R>,
  ...args: keyof Params<R> extends never
    ? [params?: Record<string, never>, query?: Record<string, string | undefined>]
    : [params: Params<R>, query?: Record<string, string | undefined>]
): string {
  const [params, query] = args as [Record<string, string> | undefined, Record<string, string | undefined> | undefined];
  const path = page.route.replace(/\[([^\]]+)\]/g, (_, k: string) => encodeURIComponent(params?.[k] ?? ""));
  const q = Object.entries(query ?? {}).filter(([, v]) => v !== undefined && v !== "");
  return q.length ? `${path}?${new URLSearchParams(q as [string, string][]).toString()}` : path;
}

export const pages = {
  /** The task list. */
  home: { id: "PAGE-001", name: "Tasks", route: "/" } as PageRef<"/">,
  /** One task. */
  taskDetail: { id: "PAGE-002", name: "Task", route: "/tasks/[id]" } as PageRef<"/tasks/[id]">,
} as const;
