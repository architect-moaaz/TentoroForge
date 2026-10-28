/**
 * The Mobile tab says why it cannot show the builds. A failed read used to look like "No mobile builds yet", which told a person
 * with a build in progress that it had gone (an expired sign-in, 2026-10-23).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

let answer: { ok: boolean; status: number; body: unknown } = { ok: true, status: 200, body: [] };

vi.mock("@/lib/api", () => ({
  authFetch: async () => ({ ok: answer.ok, status: answer.status, json: async () => answer.body }),
}));
vi.mock("@/stores/auth", () => ({ useAuthStore: (sel: (s: { token: string }) => unknown) => sel({ token: "t" }) }));
vi.mock("sonner", () => ({ toast: Object.assign(() => {}, { success: () => {}, error: () => {} }) }));
vi.mock("next/link", () => ({ default: (p: any) => React.createElement("a", { href: p.href }, p.children) }));
vi.mock("@tentoroforge/library", () => ({ QRCode: () => null }));

import { listProblemFor, MobileBuildsPanel } from "../MobileBuildsPanel";

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

describe("the list of mobile builds", () => {
  it("says the sign-in expired on a 401, not that there are no builds", async () => {
    answer = { ok: false, status: 401, body: { detail: "Invalid or expired token" } };
    await show();
    expect(host.querySelector('[data-testid="builds-problem"]')!.textContent).toContain("sign-in has expired");
    expect(host.textContent).not.toContain("No mobile builds yet");
  });

  it("says to wait on a 429 and names any other error", async () => {
    answer = { ok: false, status: 429, body: {} };
    await show();
    expect(host.querySelector('[data-testid="builds-problem"]')!.textContent).toContain("Too many requests");
    expect(listProblemFor(500)).toContain("error 500");
  });

  it("still says there are none when the read worked and the list is empty", async () => {
    answer = { ok: true, status: 200, body: [] };
    await show();
    expect(host.querySelector('[data-testid="builds-problem"]')).toBeNull();
    expect(host.textContent).toContain("No mobile builds yet");
  });
});
