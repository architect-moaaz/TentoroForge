/**
 * A breadcrumb link to `/conferences/[id]` is a dead link.
 *
 * services/page_nav.py injects Breadcrumb nodes whose hrefs come from the
 * route-tree contract, and contract keys are parameterised by design —
 * `/conferences/[id]` is the KEY for the detail route, not a URL. On a
 * two-level page that never showed (`/speakers/new` → `Speakers` →
 * `/speakers`, no param). On anything nested under a dynamic segment the
 * literal reached the browser: clicking "Conference" from
 * `/conferences/<uuid>/sessions` navigated to the string `/conferences/[id]`,
 * where the catch-all router treats `[id]` as a record id and 404s.
 *
 * Substitution has to happen at request time — only then is the concrete id
 * known — and it has to happen on the SERVER, because the alternative
 * (a client component reading `location`) renders one href during SSR and a
 * different one after hydration, which React reports as a mismatch.
 *
 * The rule when the id is unknown or the shape is ambiguous is the same one
 * the shell breadcrumb already documents: a crumb that 404s is worse than a
 * crumb that doesn't link. Drop the href, keep the label.
 */
import { describe, it, expect } from "vitest";
import { resolveCrumbHrefs } from "../src/runtime/crumbHrefs";

/** Minimal page schema carrying one Breadcrumb, nested a couple of levels
 *  deep so the walker is exercised rather than a top-level special case. */
function pageWith(items: Array<{ label: string; href?: string }>): any {
  return {
    route: "/conferences/[id]/sessions",
    children: [
      {
        type: "Stack",
        children: [{ type: "Breadcrumb", props: { items } }],
      },
    ],
  };
}

function crumbsOf(page: any): Array<{ label: string; href?: string }> {
  const found: any[] = [];
  const walk = (n: any): void => {
    if (Array.isArray(n)) return void n.forEach(walk);
    if (!n || typeof n !== "object") return;
    if (n.type === "Breadcrumb") found.push(...(n.props?.items ?? []));
    Object.values(n).forEach(walk);
  };
  walk(page);
  return found;
}

describe("the live bug", () => {
  it("substitutes the concrete id into a [id] ancestor href", () => {
    const page = pageWith([
      { label: "Conferences", href: "/conferences" },
      { label: "Conference", href: "/conferences/[id]" },
      { label: "Sessions" },
    ]);
    const out = resolveCrumbHrefs(page, "e2079592-2cdf-5669-b7c4-af979389d9d7");
    expect(crumbsOf(out)[1].href).toBe(
      "/conferences/e2079592-2cdf-5669-b7c4-af979389d9d7",
    );
  });

  it("leaves param-free hrefs byte-identical", () => {
    const page = pageWith([
      { label: "Conferences", href: "/conferences" },
      { label: "Conference", href: "/conferences/[id]" },
    ]);
    expect(crumbsOf(resolveCrumbHrefs(page, "abc"))[0].href).toBe("/conferences");
  });

  it("handles the Express-style `:id` flavour the corpus also ships", () => {
    const page = pageWith([{ label: "Conference", href: "/conferences/:id" }]);
    expect(crumbsOf(resolveCrumbHrefs(page, "xyz"))[0].href).toBe(
      "/conferences/xyz",
    );
  });

  it("substitutes a param that is not the last segment", () => {
    const page = pageWith([
      { label: "Sessions", href: "/conferences/[id]/sessions" },
    ]);
    expect(crumbsOf(resolveCrumbHrefs(page, "c1"))[0].href).toBe(
      "/conferences/c1/sessions",
    );
  });
});

describe("refusing to emit a link that would 404", () => {
  it("drops the href when no id is available", () => {
    const page = pageWith([{ label: "Conference", href: "/conferences/[id]" }]);
    const item = crumbsOf(resolveCrumbHrefs(page, undefined))[0];
    expect(item.href).toBeUndefined();
    expect(item.label).toBe("Conference"); // the crumb still reads correctly
  });

  it("drops the href when the id is an empty string", () => {
    const page = pageWith([{ label: "Conference", href: "/conferences/[id]" }]);
    expect(crumbsOf(resolveCrumbHrefs(page, ""))[0].href).toBeUndefined();
  });

  it("drops the href when two params need two different values", () => {
    // One threaded `?id=` cannot fill both slots; guessing would produce a
    // confidently wrong URL.
    const page = pageWith([
      { label: "Session", href: "/conferences/[id]/sessions/[sessionId]" },
    ]);
    expect(crumbsOf(resolveCrumbHrefs(page, "c1"))[0].href).toBeUndefined();
  });

  it("keeps a param-free href even when a sibling crumb had to be dropped", () => {
    const page = pageWith([
      { label: "Conferences", href: "/conferences" },
      { label: "Session", href: "/a/[x]/b/[y]" },
    ]);
    const items = crumbsOf(resolveCrumbHrefs(page, undefined));
    expect(items[0].href).toBe("/conferences");
    expect(items[1].href).toBeUndefined();
  });
});

describe("the pathname path — what the id alone cannot do", () => {
  // `/conferences/<id>/sessions/new` matches a LITERAL schema, so the router
  // threads no `?id=` at all. Before the pathname was passed, every crumb on
  // every create page silently lost its link.
  it("resolves a create page's ancestors with no id available", () => {
    const page = pageWith([
      { label: "Conferences", href: "/conferences" },
      { label: "Conference", href: "/conferences/[id]" },
      { label: "Sessions", href: "/conferences/[id]/sessions" },
      { label: "New" },
    ]);
    const items = crumbsOf(
      resolveCrumbHrefs(page, { pathname: "/conferences/c1/sessions/new" }),
    );
    expect(items[1].href).toBe("/conferences/c1");
    expect(items[2].href).toBe("/conferences/c1/sessions");
  });

  it("fills two distinct params from their own positions", () => {
    const page = pageWith([
      { label: "Session", href: "/conferences/[id]/sessions/[sessionId]" },
    ]);
    const out = resolveCrumbHrefs(page, {
      pathname: "/conferences/c1/sessions/s9/edit",
    });
    expect(crumbsOf(out)[0].href).toBe("/conferences/c1/sessions/s9");
  });

  it("wins over a supplied id when both are present", () => {
    const page = pageWith([{ label: "Conference", href: "/conferences/[id]" }]);
    const out = resolveCrumbHrefs(page, {
      id: "stale",
      pathname: "/conferences/fresh/sessions",
    });
    expect(crumbsOf(out)[0].href).toBe("/conferences/fresh");
  });

  it("drops the href when the crumb is longer than the current path", () => {
    // Contract and URL disagree — the crumb is not an ancestor of this page.
    const page = pageWith([
      { label: "Deep", href: "/conferences/[id]/sessions/[sid]" },
    ]);
    expect(
      crumbsOf(resolveCrumbHrefs(page, { pathname: "/conferences/c1" }))[0].href,
    ).toBeUndefined();
  });

  it("still accepts a bare id string", () => {
    const page = pageWith([{ label: "Conference", href: "/conferences/[id]" }]);
    expect(crumbsOf(resolveCrumbHrefs(page, "c1"))[0].href).toBe(
      "/conferences/c1",
    );
  });
});

describe("leaving everything else alone", () => {
  it("does not touch non-Breadcrumb hrefs", () => {
    const page = {
      children: [
        { type: "NavLink", props: { href: "/conferences/[id]", label: "x" } },
      ],
    };
    const out: any = resolveCrumbHrefs(page, "c1");
    expect(out.children[0].props.href).toBe("/conferences/[id]");
  });

  it("does not mutate the input schema", () => {
    const page = pageWith([{ label: "Conference", href: "/conferences/[id]" }]);
    const before = JSON.stringify(page);
    resolveCrumbHrefs(page, "c1");
    expect(JSON.stringify(page)).toBe(before);
  });

  it("survives a Breadcrumb with no items", () => {
    const page = { children: [{ type: "Breadcrumb", props: {} }] };
    expect(() => resolveCrumbHrefs(page, "c1")).not.toThrow();
  });

  it("survives null/undefined schemas", () => {
    expect(resolveCrumbHrefs(null, "c1")).toBeNull();
    expect(resolveCrumbHrefs(undefined, "c1")).toBeUndefined();
  });
});
