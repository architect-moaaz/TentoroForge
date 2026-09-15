import { describe, it, expect } from "vitest";
import { normaliseSchema } from "@/components/canvas/Canvas";

/**
 * Pages saved while the editor wrote `{ $binding: "expr" }` still have the
 * object on disk. `normaliseSchema` is the single production path every page
 * load goes through, so converting there means an affected page heals when it
 * is opened — no migration script, nothing for the user to do.
 *
 * This also has to happen BEFORE `validateNoLegacyBindings` runs at the commit
 * boundary, or the guard would make those pages un-openable.
 */
describe("normaliseSchema — legacy binding migration", () => {
  const load = (root: any) => normaliseSchema({ id: "p", route: "/", root });

  it("heals a legacy binding on the root node", () => {
    const out = load({ id: "btn", type: "Button", props: { label: { $binding: "items[0].name" } } });
    expect(out.root.props.label).toBe("{{items[0].name}}");
  });

  it("heals bindings on nested children and inside named slots", () => {
    const out = load({
      id: "shell", type: "AppShell",
      children: [{ id: "b", type: "Button", props: { label: { $binding: "a.b" } } }],
      slots: { sidebar: [{ id: "t", type: "Text", props: { content: { $binding: "c.d" } } }] },
    });
    expect(out.root.children[0].props.label).toBe("{{a.b}}");
    expect(out.root.slots.sidebar[0].props.content).toBe("{{c.d}}");
  });

  it("turns a toggled-but-never-filled bind into \"\", not \"{{}}\"", () => {
    const out = load({ id: "btn", type: "Button", props: { label: { $binding: "" } } });
    expect(out.root.props.label).toBe("");
  });

  it("leaves working schemas alone", () => {
    const out = load({
      id: "btn", type: "Button",
      props: { label: "{{user.name}}", variant: "primary", disabled: false },
    });
    expect(out.root.props).toEqual({ label: "{{user.name}}", variant: "primary", disabled: false });
  });

  it("still injects ids and wraps the legacy top-level children format", () => {
    // Migration must not disturb what normaliseSchema already did.
    const out = normaliseSchema({ id: "p", route: "/", children: [{ type: "Text", props: {} }] });
    expect(out.root.type).toBe("Stack");
    expect(out.root.children[0].id).toBeTruthy();
  });
});
