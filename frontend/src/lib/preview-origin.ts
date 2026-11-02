import { useEffect, useState } from "react";

/**
 * Where previews are served: an origin of their own, never the platform's
 * (`services/preview_origin.py`). The preview runs the app's code; at the
 * platform's origin it could read the person's sign-in. The backend says
 * which origin it is, once per page load.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL
  || (typeof window !== "undefined" && window.location.hostname === "localhost" ? "http://localhost:6500" : "");

let known: Promise<string> | null = null;

export function previewOrigin(): Promise<string> {
  if (!known) {
    known = fetch(`${API_BASE}/api/preview/origin`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((b: { origin: string }) => b.origin.replace(/\/$/, ""));
    known.catch(() => { known = null; });
  }
  return known;
}

/** The preview origin, or null until it is known. */
export function usePreviewOrigin(): string | null {
  const [origin, setOrigin] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    previewOrigin().then((o) => { if (live) setOrigin(o); }).catch(() => {});
    return () => { live = false; };
  }, []);
  return origin;
}
