// Last-resort workflow dispatch used when no WorkflowDispatcherContext value is
// available. In standalone generated apps the dispatch provider and the library
// can end up resolving DIFFERENT copies of @tentoroforge/renderer (vendored
// `file:` deps + transpilePackages), so React Context identity doesn't match and
// useContext(WorkflowDispatcherContext) returns undefined. Rather than silently
// no-op a form submit, POST straight to the generated workflow route — same
// envelope the real dispatch uses ({ input }) — then reload so server-rendered
// data reflects the change. Safe no-op during SSR.
export async function fallbackDispatch(
  workflow: string,
  args?: Record<string, unknown>,
): Promise<void> {
  if (typeof window === "undefined") return;
  try {
    const res = await fetch(`/api/workflows/${encodeURIComponent(workflow)}/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: args ?? {} }),
    });
    let ok = res.ok;
    try {
      const body = await res.clone().json();
      if (body && typeof body.status === "string") ok = body.status === "completed";
    } catch {
      /* non-JSON body — fall back to HTTP status */
    }
    if (ok) {
      window.location.reload();
    } else {
      // eslint-disable-next-line no-console
      console.error(`[forge] workflow ${workflow} did not complete`, res.status);
    }
  } catch (e) {
    // eslint-disable-next-line no-console
    console.error(`[forge] workflow ${workflow} dispatch failed`, e);
  }
}
