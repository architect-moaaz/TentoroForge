// Workflows in the JIT preview: `/api/workflows/<id>/execute` is answered here,
// not by the app, and every run is reported to the editor as an action trace
// (PREVIEW-005). Nothing reaches a database.
export function installPreviewFetch() {
  const real = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const m = /\/api\/workflows\/([^/]+)\/execute/.exec(url);
    if (!m) return real(input, init);
    const t0 = performance.now();
    let body: any = {};
    try { body = init?.body ? JSON.parse(String(init.body)) : {}; } catch { /* not json */ }
    await new Promise((r) => setTimeout(r, 350));
    const result = { status: "completed", result: { record: { id: "sample-new-1", ...(body.input ?? {}) } }, log: ["Ran in preview with sample data"] };
    window.parent?.postMessage({ type: "forge-editor:action", payload: {
      workflow: decodeURIComponent(m[1]), input: body.input ?? {}, status: 200, ok: true, elapsedMs: Math.round(performance.now() - t0), mocked: true, output: result.result,
    } }, window.location.origin);
    return new Response(JSON.stringify(result), { status: 200, headers: { "Content-Type": "application/json" } });
  };
}
