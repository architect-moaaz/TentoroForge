/**
 * Where a published app runs: a choice until its first publish (its
 * organisation's default marked), and once its database exists, the region it
 * is in — said, not offered (2026-10-22).
 */
import { describe, it, expect, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const puts: [string, unknown][] = [];
vi.mock("@/lib/api", () => ({
  api: {
    put: async (u: string, b: any) => {
      puts.push([u, b]);
      return { region: b.region, label: b.region, locked: false, org_default: "ap-singapore", regions: [] };
    },
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { DeployRegionPicker, type RegionState } from "../PublishSides";

const regions = [
  { id: "default", label: "Default — US East (Ohio)" },
  { id: "ap-singapore", label: "Asia Pacific (Singapore) — nearest to India" },
  { id: "eu-london", label: "Europe (London)" },
];

function mount(state: RegionState) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  let root!: Root;
  act(() => {
    root = createRoot(el);
    root.render(
      <QueryClientProvider client={new QueryClient()}>
        <DeployRegionPicker projectId="p1" state={state} />
      </QueryClientProvider>,
    );
  });
  return { el, unmount: () => act(() => root.unmount()) };
}

describe("the region an app is published in", () => {
  it("is a choice before the first publish, the organisation's default marked", async () => {
    const v = mount({ region: "ap-singapore", label: "Singapore", locked: false, org_default: "ap-singapore", regions });
    const select = v.el.querySelector("select") as HTMLSelectElement;
    expect(select.value).toBe("ap-singapore");
    expect(v.el.textContent).toContain("your organisation's default");
    expect(v.el.textContent).toContain("Its first publish fixes it");
    await act(async () => {
      select.value = "eu-london";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(puts.at(-1)).toEqual(["/api/projects/p1/deploy-region", { region: "eu-london" }]);
    v.unmount();
  });

  it("is said, not offered, once the app's database exists", () => {
    const v = mount({ region: "default", label: "Default — US East (Ohio)", locked: true, org_default: "ap-singapore", regions });
    expect(v.el.querySelector("select")).toBeNull();
    expect(v.el.textContent).toContain("Runs in Default — US East (Ohio)");
    v.unmount();
  });
});
