/**
 * What the panel can see of the preview when a person reports a problem:
 * the screen they were on, the device size the frame emulates, the viewport.
 *
 * A request to Smith carried only words, so the trials ran as whoever the
 * model guessed; "Add to cart works — I ran it directly" answered a button
 * that never called it (E-commerce, 2026-10-09). The preview frame records
 * its route as it navigates; the panel sends it with every message.
 */
export interface PreviewReport {
  route?: string;
  device?: string;
  viewport?: { width: number; height: number };
}

const state: PreviewReport = {};

/** The preview frame's current route, read off its document when it loads. */
export function rememberPreview(
  frame: HTMLIFrameElement | null,
  device?: string,
  size?: { width: number | string; height: number | string },
) {
  if (device) state.device = device;
  // The frame's emulated size is "390px" or "100%"; only a real size is a viewport.
  const w = size ? parseInt(String(size.width), 10) : NaN;
  const h = size ? parseInt(String(size.height), 10) : NaN;
  if (Number.isFinite(w) && Number.isFinite(h)) state.viewport = { width: w, height: h };
  try {
    const path = frame?.contentWindow?.location?.pathname;
    if (path) {
      // The proxy serves the app under `/api/projects/<id>/preview/...`; the
      // app's own route is what follows.
      const m = path.match(/\/preview(\/.*)?$/);
      state.route = m ? (m[1] || "/") : path;
    }
  } catch {
    // Cross-origin: the route is not ours to read.
  }
}

/** What to send with a message; empty when nothing is known. */
export function previewReport(): PreviewReport | undefined {
  return Object.keys(state).length ? { ...state } : undefined;
}
