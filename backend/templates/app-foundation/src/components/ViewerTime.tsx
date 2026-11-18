"use client";
// THE VIEWER'S TIME ZONE AND LANGUAGE, told to the server (`forge-tz`), so the
// dates it draws match the ones this browser draws (`lib/viewer-time.ts`).
// Written when it changes — a laptop that travels, a language switched.
// Renders nothing. Platform runtime — do not remove.
import { useEffect } from "react";

export function ViewerTime() {
  useEffect(() => {
    try {
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      const value = encodeURIComponent(`${zone}|${navigator.language || ""}`);
      if (document.cookie.split("; ").includes(`forge-tz=${value}`)) return;
      document.cookie = `forge-tz=${value}; path=/; max-age=31536000; samesite=lax`;
    } catch {
      /* no cookies here — the server falls back to the address's zone */
    }
  }, []);
  return null;
}
