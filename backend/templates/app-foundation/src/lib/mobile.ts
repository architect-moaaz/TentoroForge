// Written by the Blueprint projection (project_pwa). This default: installable,
// no push. Edit the Blueprint, not this file.
export interface MobilePolicy {
  installable: boolean;
  display: "standalone" | "fullscreen" | "minimal-ui" | "browser";
  orientation: "any" | "portrait" | "landscape";
  push: boolean;
  store: { enabled: boolean; bundleId: string | null };
  /** The address the installed app opens on. */
  startUrl: string;
  themeColor: string;
  backgroundColor: string;
}
export const MOBILE: MobilePolicy = {
  installable: true, display: "standalone", orientation: "any", push: false,
  store: { enabled: false, bundleId: null }, startUrl: "/", themeColor: "#0f172a", backgroundColor: "#ffffff",
};
