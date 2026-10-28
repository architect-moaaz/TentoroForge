/**
 * The Mobile tab offers the install of a finished Android app: a code to scan, a link to open, the phone steps.
 * Nothing is offered until a build has finished with a file to install.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

let builds: any[] = [];

vi.mock("@/lib/api", () => ({
  authFetch: async () => ({ ok: true, json: async () => builds }),
}));
vi.mock("@/stores/auth", () => ({ useAuthStore: (sel: (s: { token: string }) => unknown) => sel({ token: "t" }) }));
vi.mock("sonner", () => ({ toast: Object.assign(() => {}, { success: () => {}, error: () => {} }) }));
vi.mock("next/link", () => ({ default: (p: any) => React.createElement("a", { href: p.href }, p.children) }));
vi.mock("@tentoroforge/library", () => ({
  QRCode: (p: { value: string }) => React.createElement("svg", { "data-testid": "qr", "data-value": p.value }),
}));

import { MobileBuildsPanel } from "../MobileBuildsPanel";

const APK = "https://expo.dev/artifacts/eas/example.apk";
const row = (over: Record<string, unknown>) => ({
  id: "b1", project_id: "p1", profile: "preview", platform: "android", status: "completed", eas_build_id: "e1",
  artifact_url: APK, logs_url: null, error_message: null, created_at: "2026-10-21T10:00:00Z", updated_at: "2026-10-21T10:10:00Z",
  completed_at: "2026-10-21T10:10:00Z", ...over,
});

let host: HTMLDivElement;
let root: Root;

async function show() {
  await act(async () => {
    root.render(React.createElement(MobileBuildsPanel, { projectId: "p1", orgId: "o1" }));
  });
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("the install card", () => {
  it("is offered for a finished Android build, with a code, a download link and the iPhone steps", async () => {
    builds = [row({})];
    await show();
    const card = host.querySelector('[data-testid="install-card"]');
    expect(card).not.toBeNull();
    expect(card!.textContent).toContain("Install on Android");
    expect(card!.textContent).toContain("Add to Home Screen");
    expect(host.querySelector('[data-testid="qr"]')!.getAttribute("data-value")).toBe(APK);
    const link = Array.from(card!.querySelectorAll("a")).find((a) => a.textContent?.includes("Download app"));
    expect(link?.getAttribute("href")).toBe(APK);
  });

  it("is not offered while the build is still running or after it failed", async () => {
    builds = [row({ status: "in_progress", artifact_url: null }), row({ id: "b2", status: "failed", artifact_url: null })];
    await show();
    expect(host.querySelector('[data-testid="install-card"]')).toBeNull();
  });

  it("is not offered for a finished build that has no file to install", async () => {
    builds = [row({ artifact_url: null })];
    await show();
    expect(host.querySelector('[data-testid="install-card"]')).toBeNull();
  });
});
