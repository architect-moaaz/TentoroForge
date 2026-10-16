/**
 * The app's own address: the records to add while it waits, Check now asks
 * the server, and adding an address posts it. One panel, shown in App
 * settings → Domains and in the Publish dialog.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const waiting = {
  domains: [
    {
      name: "app.acme.com", kind: "subdomain", main: true, status: "waiting",
      detail: "Waiting for the DNS record.", checkedAt: null, works: null, worksDetail: "",
      records: [{ host: "app.acme.com", type: "CNAME", value: "cname.vercel-dns.com", why: "points app.acme.com at Vercel" }],
    },
  ],
  oldAddress: "redirect",
  vercelAddress: "https://shop.vercel.app",
  mainAddress: "https://shop.vercel.app",
  elsewhere: [],
  appsDomain: "",
};
const live = { ...waiting, domains: [{ ...waiting.domains[0], status: "live", records: [], detail: "" }], mainAddress: "https://app.acme.com" };

const tentoro = {
  ...waiting,
  domains: [{ name: "shop.apps.tentoro.ai", kind: "tentoro", main: true, status: "live", detail: "", records: [], checkedAt: null, works: true, worksDetail: "" }],
  appsDomain: "apps.tentoro.ai",
};

const apiGet = vi.fn(async (_: string) => waiting as unknown);
const apiPut = vi.fn(async (_: string, __?: unknown) => tentoro as unknown);
const apiPost = vi.fn(async (_: string, __?: unknown) => live as unknown);
vi.mock("@/lib/api", () => ({
  api: {
    get: (u: string) => apiGet(u),
    post: (u: string, b?: unknown) => apiPost(u, b),
    put: (u: string, b?: unknown) => apiPut(u, b),
    delete: vi.fn(async () => waiting),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const nav = { search: new URLSearchParams(), replaced: [] as string[] };
vi.mock("next/navigation", () => ({
  useParams: () => ({ orgId: "o1" }),
  useSearchParams: () => nav.search,
  useRouter: () => ({ replace: (u: string) => nav.replaced.push(u) }),
  usePathname: () => "/org/o1/projects/p1",
}));

import { DomainsPanel } from "../DomainsPanel";

let root: Root;
let host: HTMLDivElement;

async function render() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={qc}>
        <DomainsPanel projectId="p1" />
      </QueryClientProvider>,
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

const button = (label: string) =>
  [...host.querySelectorAll("button")].find((b) => b.textContent?.includes(label)) as HTMLButtonElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  apiGet.mockClear();
  apiPost.mockClear();
  apiPut.mockClear();
  apiGet.mockImplementation(async () => waiting);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("DomainsPanel", () => {
  it("shows the record to add while the address waits", async () => {
    await render();
    expect(apiGet).toHaveBeenCalledWith("/api/projects/p1/domains");
    expect(host.textContent).toContain("app.acme.com");
    expect(host.textContent).toContain("Waiting for DNS");
    expect(host.textContent).toContain("CNAME");
    expect(host.textContent).toContain("cname.vercel-dns.com");
  });

  it("Check now asks the server and shows what it found", async () => {
    await render();
    await act(async () => { button("Check now").click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/domains/app.acme.com/check", undefined);
    expect(host.textContent).toContain("Live");
    expect(host.textContent).not.toContain("cname.vercel-dns.com");
  });

  it("adds an address", async () => {
    await render();
    const input = host.querySelector("input") as HTMLInputElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(input, "www.acme.com");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { button("Add domain").click(); });
    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/domains", { name: "www.acme.com" });
  });

  it("renames the Tentoro address and never offers to remove it", async () => {
    apiGet.mockImplementation(async () => tentoro);
    await render();
    expect(button("Remove")).toBeUndefined();
    await act(async () => { button("Rename").click(); });
    const input = host.querySelector("#domain-rename-p1") as HTMLInputElement;
    expect(input.value).toBe("shop");
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(input, "aqua");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const submit = [...host.querySelectorAll("form button[type=submit]")].find((b) => b.textContent?.includes("Rename")) as HTMLButtonElement;
    await act(async () => { submit.click(); });
    expect(apiPut).toHaveBeenCalledWith("/api/projects/p1/domains/tentoro", { name: "aqua" });
  });

  it("adds the records at a connected DNS account, and replaces only when asked", async () => {
    apiGet.mockImplementation(async () => ({ ...waiting, dnsAccounts: ["Cloudflare"] }));
    const conflict = {
      ...waiting, dnsAccounts: ["Cloudflare"],
      result: { written: false, conflicts: true, replaceable: true, provider: "Cloudflare",
                message: "I did not change anything: A app.acme.com → 1.2.3.4 is already there at Cloudflare." },
    };
    apiPost.mockImplementationOnce(async () => conflict);
    await render();
    await act(async () => { button("Add the records for me").click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/domains/app.acme.com/records", { replace: false });
    expect(host.textContent).toContain("1.2.3.4 is already there");
    apiPost.mockImplementationOnce(async () => ({ ...live, dnsAccounts: ["Cloudflare"],
      result: { written: true, conflicts: false, provider: "Cloudflare", message: "Added" } }));
    await act(async () => { button("Replace at Cloudflare").click(); });
    expect(apiPost).toHaveBeenLastCalledWith("/api/projects/p1/domains/app.acme.com/records", { replace: true });
  });

  it("says where the domain's DNS is when no account is connected", async () => {
    apiGet.mockImplementation(async () => ({
      ...waiting, dnsAccounts: [], domains: [{ ...waiting.domains[0], dnsHost: "Cloudflare" }],
    }));
    await render();
    expect(host.textContent).toContain("acme.com’s DNS is at Cloudflare");
    expect(host.querySelector('a[href="/org/o1/settings/integrations"]')).not.toBeNull();
    expect(button("Add the records for me")).toBeUndefined();
  });

  it("gives each organisation an address when the app has several", async () => {
    apiGet.mockImplementation(async () => ({ ...waiting, organisations: { available: true, signIn: "shared" } }));
    apiPost.mockImplementationOnce(async () => ({ ...waiting, organisations: { available: true, signIn: "shared" } }));
    await render();
    const input = host.querySelector("#domain-orgs-p1") as HTMLInputElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      set.call(input, "clinicapp.com");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { button("Give each organisation an address").click(); });
    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/domains/organisations", { name: "clinicapp.com" });
  });

  it("offers no address per organisation to an app of one", async () => {
    await render();
    expect(host.querySelector("#domain-orgs-p1")).toBeNull();
  });

  it("sends the owner to their DNS provider to approve, and checks when they come back", async () => {
    apiGet.mockImplementation(async () => ({ ...waiting, domains: [{ ...waiting.domains[0], connect: "GoDaddy" }] }));
    apiPost.mockImplementationOnce(async () => ({ url: "https://dcc.godaddy.com/manage/v2/apply?x=1", provider: "GoDaddy" }));
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, assign }, writable: true });
    await render();
    await act(async () => { button("Connect with GoDaddy").click(); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/domains/app.acme.com/connect", undefined);
    expect(assign).toHaveBeenCalledWith("https://dcc.godaddy.com/manage/v2/apply?x=1");

    act(() => root.unmount());
    root = createRoot(host);
    nav.search = new URLSearchParams("settings=domains&dc=app.acme.com&state=s1");
    apiPost.mockClear();
    await render();
    expect(apiPost).toHaveBeenCalledWith("/api/projects/p1/domains/app.acme.com/check", undefined);
    expect(nav.replaced).toContain("/org/o1/projects/p1");
    nav.search = new URLSearchParams();
  });

  it("shows how to add the record at the owner's provider, and what exactly is wrong", async () => {
    const guide = {
      provider: "GoDaddy",
      providers: ["GoDaddy", "Cloudflare", "Another provider"],
      steps: {
        GoDaddy: ["Sign in at godaddy.com and open My Products.", "Type CNAME · Name app · Value cname.vercel-dns.com"],
        Cloudflare: ["Sign in at dash.cloudflare.com", "Type CNAME · Name app · Target/Content cname.vercel-dns.com · Proxy status: DNS only (grey cloud)"],
        "Another provider": ["Sign in where acme.com's DNS is managed"],
      },
      tips: { GoDaddy: ["Type only app as the name"], Cloudflare: ["Proxy status must be DNS only"], "Another provider": [] },
    };
    apiGet.mockImplementation(async () => ({
      ...waiting,
      domains: [{ ...waiting.domains[0], guide,
                  problems: [{ code: "in-the-way", says: "app.acme.com already has an A record (203.0.113.7). Delete it." }] }],
    }));
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("already has an A record");
    expect(host.textContent).toContain("How to add this at GoDaddy");
    expect(host.textContent).toContain("open My Products");
    const select = host.querySelector("select#guide-app-acme-com") as HTMLSelectElement;
    await act(async () => {
      select.value = "Cloudflare";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.textContent).toContain("How to add this at Cloudflare");
    expect(host.textContent).toContain("DNS only (grey cloud)");
  });
});
