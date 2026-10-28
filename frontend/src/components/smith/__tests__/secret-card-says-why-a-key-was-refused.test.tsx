/**
 * The key box says why a key was not saved. A 403 is either not being an admin, or
 * integrations switched off for the organisation; "ask an admin" is wrong for the second.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
vi.mock("next/navigation", () => ({ useParams: () => ({ orgId: "o1" }) }));

import { SecretCard } from "../SecretCard";

const FIELD = { provider: "uxpilot", key: "UXPILOT_API_KEY", label: "UX Pilot API key", saved: "UX Pilot key saved" } as any;
let root: Root;
let host: HTMLDivElement;

async function submitAndRead(status: number, detail: string): Promise<string> {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail }), { status })));
  await act(async () => { root.render(<SecretCard field={FIELD} onSaved={() => {}} />); });
  const input = host.querySelector("input")!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "ep_" + "Ab3dEf6hIj9kLmNo");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  for (let i = 0; i < 5; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  return host.querySelector('[role="alert"]')?.textContent ?? "";
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

describe("the key box", () => {
  it("says integrations are switched off, not that an admin is needed", async () => {
    const said = await submitAndRead(403, "Integrations is not enabled for your organisation. Ask the platform administrator.");
    expect(said).toContain("not enabled for your organisation");
    expect(said).not.toContain("Only an organisation admin");
    expect(said).toContain("Forge UI Designer instead");
  });

  it("still says an admin is needed when that is the refusal", async () => {
    const said = await submitAndRead(403, "Admin role required");
    expect(said).toContain("Only an organisation admin can save integration keys");
  });
});
