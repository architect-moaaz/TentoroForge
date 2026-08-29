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
    // A REDIRECT IS NOT A RESULT. When the execute route is gated and there is
    // no session, it answers 307 to /login; fetch follows it, the login page
    // returns 200 HTML, `res.ok` is true, `.json()` throws, the catch below
    // leaves `ok` true — and this reloaded the page and reported success. A
    // user pressing "Add plant" saw the page blink and nothing else, which is
    // the worst available outcome: the write never happened and nothing said
    // so. `redirected` is true here and `res.url` is the login page; either
    // alone distinguishes it, and neither was being read.
    if (res.redirected) {
      // eslint-disable-next-line no-console
      console.error(
        `[forge] workflow ${workflow} was not run — the request was redirected ` +
          `to ${res.url}. This usually means the session has expired or the ` +
          `workflow route requires sign-in.`,
      );
      return;
    }
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
