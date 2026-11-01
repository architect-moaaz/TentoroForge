import { authFetch } from "@/lib/api";

/**
 * A project's live stream, opened with a ticket.
 *
 * EventSource sends no header, so these streams were open to anyone who knew
 * the project id — which is in every preview address (audit, 2026-11-01). A
 * member now asks for a ticket (`POST /api/projects/:id/stream-ticket`) and
 * opens the stream with it. The ticket opens only this project's streams and
 * lasts a working day; when the stream is refused (an old ticket), a new one
 * is asked for and the stream opened again.
 *
 * Streams connect straight to the backend: Next's dev proxy buffers them.
 *
 * `attach` adds the listeners and returns what removes them. The function
 * returned here closes the stream for good.
 */
export function openProjectStream(
  projectId: string,
  path: string,
  attach: (es: EventSource) => () => void,
): () => void {
  const apiBase = process.env.NEXT_PUBLIC_API_URL
    || (typeof window !== "undefined" && window.location.hostname === "localhost" ? "http://localhost:6500" : "");
  let es: EventSource | null = null;
  let detach: (() => void) | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let tries = 0;

  const drop = () => {
    detach?.();
    detach = null;
    es?.close();
    es = null;
  };

  const open = async () => {
    if (closed) return;
    try {
      const res = await authFetch(`${apiBase}/api/projects/${projectId}/stream-ticket`, { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      const { ticket } = (await res.json()) as { ticket: string };
      if (closed) return;
      const sep = path.includes("?") ? "&" : "?";
      es = new EventSource(`${apiBase}${path}${sep}ticket=${encodeURIComponent(ticket)}`);
      detach = attach(es);
      es.addEventListener("open", () => { tries = 0; });
      es.addEventListener("error", () => {
        // A network drop is retried by the browser itself; a refused stream closes.
        if (es?.readyState === EventSource.CLOSED) again();
      });
    } catch {
      again();
    }
  };

  const again = () => {
    drop();
    if (closed) return;
    tries += 1;
    retry = setTimeout(() => void open(), Math.min(30_000, 1000 * 2 ** Math.min(tries, 5)));
  };

  void open();
  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    drop();
  };
}
