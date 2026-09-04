/**
 * RECORD SCOPE — the Access tab's row_access authoring.
 *
 * Written the way backend/templates/runtime/__tests__/run-ownership-tests.sh
 * is: the real component and the real `conditionToFeel` run, with only the
 * transport stubbed, so a regression fails here rather than a paraphrase of
 * the component passing while the component itself rots.
 *
 * The bug being pinned is not a rendering one. RecordScopeEditor used to hold
 * a closed list of scope kinds in `useState` and post nothing, so adding a
 * scope rule looked exactly like saving one. Every assertion below is
 * therefore about what crosses the network, or about what the panel says
 * concerning the two semantics the data engine enforces — grants UNION, and
 * an unaddressed role reads nothing.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RecordScopeEditor } from "@/components/rules/RecordScopeEditor";
import { conditionToFeel } from "@/lib/condition-to-feel";
import type { ConditionExpression } from "@/types/rules";

// ---- jsdom polyfills radix needs -------------------------------------------
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  (window as any).matchMedia = (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  });
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof Element !== "undefined" && !Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
}

// ---------------------------------------------------------------------------
// The condition an author builds is the condition the engine compiles
// ---------------------------------------------------------------------------

const node = (
  field: string,
  operator: string,
  value = "",
): ConditionExpression =>
  ({ id: "c1", field, operator, value } as ConditionExpression);

describe("record scope — the condition the builder produces", () => {
  it("keeps `user.<field>` a reference to the acting user, not a string", () => {
    // Quoted, this is `createdByUserId = "user.id"` — a comparison against a
    // literal that no row carries. It matches nothing, and nothing anywhere
    // reports why. The whole point of a scope rule is that it resolves from
    // the session, which is what row-access-sql's `named()` does with a bare
    // `user.id`.
    expect(conditionToFeel(node("createdByUserId", "equals", "user.id")))
      .toBe("createdByUserId = user.id");
    expect(conditionToFeel(node("departmentId", "equals", "user.departmentId")))
      .toBe("departmentId = user.departmentId");
  });

  it("still quotes ordinary values, including ones that merely look dotted", () => {
    expect(conditionToFeel(node("status", "equals", "active")))
      .toBe('status = "active"');
    expect(conditionToFeel(node("host", "equals", "user.example.com")))
      .toBe('host = "user.example.com"');
    // Not addressable in the session or the SQL compiler — a literal is the
    // honest encoding, and it fails visibly rather than reading as null.
    expect(conditionToFeel(node("orgId", "equals", "user.profile.org")))
      .toBe('orgId = "user.profile.org"');
  });

  it("compiles an empty condition to `true` — the grant that reads every row", () => {
    // Fail-closed only leaves an escape hatch if "everything" is expressible.
    expect(conditionToFeel(null)).toBe("true");
  });
});

// ---------------------------------------------------------------------------
// The panel, against the real rules API
// ---------------------------------------------------------------------------

const RULES = [
  {
    id: "rule-own",
    project_id: "p1",
    name: "Managers read their own decisions",
    rule_type: "row_access",
    model_name: "applications",
    field_name: null,
    config: {
      when: null,
      whenFeel: "createdByUserId = user.id",
      roles: ["hiring_manager"],
    },
    is_active: true,
    created_at: "",
    updated_at: "",
  },
  {
    id: "rule-all",
    project_id: "p1",
    name: "Recruiters read everything",
    rule_type: "row_access",
    model_name: "applications",
    field_name: null,
    config: { when: null, whenFeel: "true", roles: ["recruiter"] },
    is_active: true,
    created_at: "",
    updated_at: "",
  },
];

const APP_MODEL = {
  database: {
    tables: [
      {
        name: "applications",
        columns: [{ name: "id" }, { name: "createdByUserId" }, { name: "status" }],
      },
    ],
  },
};

const ROLES = [
  { id: "r1", name: "recruiter" },
  { id: "r2", name: "hiring_manager" },
  { id: "r3", name: "finance" },
];

interface Call { method: string; path: string; body?: any }

let calls: Call[];
let container: HTMLDivElement;
let root: Root;

function stubFetch(rules: unknown[] = RULES) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = String(url).replace("http://localhost:6500", "");
    const method = init.method ?? "GET";
    calls.push({
      method,
      path,
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    });

    const json = (data: unknown) =>
      ({ ok: true, status: 200, json: async () => data }) as Response;

    if (path.startsWith("/api/projects/p1/rules?")) return json(rules);
    if (path.startsWith("/api/projects/p1/rules/")) {
      return { ok: true, status: 204, json: async () => undefined } as Response;
    }
    if (path === "/api/projects/p1/app-model") return json(APP_MODEL);
    if (path === "/api/orgs/o1/roles") return json(ROLES);
    return json([]);
  }));
}

async function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <RecordScopeEditor projectId="p1" orgId="o1" />
      </QueryClientProvider>,
    );
  });
  // The queries resolve in sequence, not together: the model select picks a
  // default once app-model lands, and only then does the rules query start.
  await flush();
}

/** Let every queued query settle and its render commit. */
async function flush(turns = 6) {
  for (let i = 0; i < turns; i++) {
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  }
}

function click(el: Element | null) {
  if (!el) throw new Error("element not found");
  return act(async () => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function clickAndFlush(el: Element | null) {
  await click(el);
  await flush();
}

const byTestId = (id: string) =>
  document.querySelector(`[data-testid="${id}"]`);

beforeEach(() => {
  calls = [];
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  stubFetch();
});

afterEach(async () => {
  await act(async () => { root.unmount(); });
  container.remove();
  vi.unstubAllGlobals();
});

describe("RecordScopeEditor", () => {
  it("reads the row rules for the selected model from the rules API", async () => {
    await mount();

    const listed = calls.find((c) => c.path.startsWith("/api/projects/p1/rules?"));
    expect(listed).toBeDefined();
    // Both filters, or the panel is showing another model's rules and every
    // other rule type alongside them.
    expect(listed!.path).toContain("rule_type=row_access");
    expect(listed!.path).toContain("model_name=applications");

    expect(container.textContent).toContain("Managers read their own decisions");
    // The compiled condition is what the engine puts in the WHERE clause, so
    // it is what the panel shows — not a scope-kind label standing in for it.
    expect(container.textContent).toContain("createdByUserId = user.id");
    expect(container.textContent).toContain("hiring_manager");
  });

  it("names the roles that no rule addresses, because they read nothing", async () => {
    await mount();
    // finance is in the org and in no rule: fail-closed, so it reads no rows.
    expect(container.textContent).toContain("No rule names finance");
    // The two roles that ARE granted must not be reported as shut out.
    expect(container.textContent).not.toContain("No rule names recruiter");
  });

  it("says nothing about unaddressed roles while the model has no rules", async () => {
    stubFetch([]);
    await mount();
    expect(container.textContent).not.toContain("No rule names");
    expect(container.textContent).toContain("every role reads");
  });

  it("explains that rules union rather than narrow", async () => {
    await mount();
    expect(container.textContent).toContain(
      "adding another one only ever widens it",
    );
  });

  it("deletes through the rules API instead of dropping local state", async () => {
    await mount();
    await clickAndFlush(byTestId("scope-delete-rule-own"));

    const del = calls.find((c) => c.method === "DELETE");
    expect(del).toBeDefined();
    expect(del!.path).toBe("/api/projects/p1/rules/rule-own");
    // And it re-reads, so the list reflects the server rather than a guess.
    expect(
      calls.filter((c) => c.path.startsWith("/api/projects/p1/rules?")).length,
    ).toBeGreaterThan(1);
    // Deleting a row must not also open that row's editor.
    expect(document.body.textContent).not.toContain("Edit Rule:");
  });

  it("opens the row-access form for a new rule on the selected model", async () => {
    await mount();
    await clickAndFlush(byTestId("scope-add"));

    // RowAccessRuleForm's own labels — the dialog opened on `row_access`, not
    // on the validation rule the dialog otherwise defaults to.
    expect(document.body.textContent).toContain("Grants to");
    expect(document.body.textContent).toContain("Readable when");
    expect(document.body.textContent).not.toContain("Edit Rule:");
  });

  it("opens an existing rule for editing", async () => {
    await mount();
    await clickAndFlush(byTestId("scope-rule-rule-own"));
    expect(document.body.textContent).toContain(
      "Edit Rule: Managers read their own decisions",
    );
  });
});
