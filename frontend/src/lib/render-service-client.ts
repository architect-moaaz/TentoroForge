// frontend/src/lib/render-service-client.ts
const RENDER_SERVICE_URL =
  process.env.NEXT_PUBLIC_RENDER_SERVICE_URL ?? "http://localhost:6502";

export interface RenderResponse {
  pngBase64: string;
  pngBytes: number;
  htmlSnapshot: string;
  accessibilityTree: string;
  renderTimeMs: number;
  consoleWarnings: string[];
  networkFailures: string[];
}

export async function renderPage(
  projectId: string,
  pageRoute: string,
  viewport: "mobile" | "tablet" | "desktop" = "desktop",
): Promise<RenderResponse | null> {
  try {
    const r = await fetch(`${RENDER_SERVICE_URL}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, pageRoute, viewport }),
    });
    if (!r.ok) return null;
    return (await r.json()) as RenderResponse;
  } catch {
    return null;
  }
}
