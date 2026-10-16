/**
 * A feature the organisation lacks stays where it was — a locked Publish
 * button, a locked tab panel — and explains itself instead of acting.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toastInfo = vi.fn();
vi.mock("sonner", () => ({ toast: { info: (...a: unknown[]) => toastInfo(...a), success: vi.fn(), error: vi.fn() } }));

import { LockedPanel } from "@/components/features/Locked";
import { PublishButton } from "@/components/deploy/PublishButton";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | undefined; let el: HTMLDivElement;
beforeEach(() => { toastInfo.mockReset(); el = document.createElement("div"); document.body.appendChild(el); });
afterEach(() => { if (root) act(() => root!.unmount()); root = undefined; el.remove(); vi.unstubAllGlobals(); });

describe("a locked feature", () => {
  it("shows a panel that names the feature and who can open it", () => {
    act(() => { root = createRoot(el); root!.render(<LockedPanel name="Code tab" />); });
    expect(el.textContent).toContain("Code tab is locked");
    expect(el.textContent).toContain("Ask the platform administrator");
  });

  it("keeps the Publish button, locked, and explains instead of publishing", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const body = url.endsWith("/deployments/latest") ? null : { status: "ready" };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await act(async () => {
      root = createRoot(el);
      root!.render(<QueryClientProvider client={qc}><PublishButton projectId="p1" orgId="o1" lockedWeb lockedMobile /></QueryClientProvider>);
    });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const publish = el.querySelector('button[data-locked="publish"]') as HTMLButtonElement;
    expect(publish).not.toBeNull();
    expect(publish.textContent).toContain("Publish");
    expect(publish.title).toContain("not enabled for your organisation");
    act(() => publish.click());
    expect(toastInfo).toHaveBeenCalledWith(expect.stringContaining("Publish to the web is not enabled"));
    expect(document.body.textContent).not.toContain("Publish your app");  // the dialog did not open
    const mobile = el.querySelector('button[data-locked="mobile_builds"]') as HTMLButtonElement;
    act(() => mobile.click());
    expect(toastInfo).toHaveBeenLastCalledWith(expect.stringContaining("Mobile builds is not enabled"));
  });
});
