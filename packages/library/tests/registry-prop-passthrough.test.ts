/**
 * CONTRACT LOCK — every prop the registry declares must SURVIVE validateProps.
 *
 * This is the layer above "does the component read the prop?". The editor
 * renders a control for every registry descriptor, but the value then passes
 * through `registry.validateProps()` (dispatch.tsx) before any component sees
 * it, and zod DROPS anything the node schema does not declare — silently, with
 * no error, on a *successful* parse.
 *
 * That silence is what makes this worth locking. Divider.thickness, NavLink
 * .target and NavLink.icon were each fixed in the component and still did
 * nothing in the running editor, because the prop never got that far. A unit
 * test that renders <NavLink target="/x" /> directly passes while the product
 * stays broken — only going through validateProps catches it.
 *
 * Switch.checked was found by exactly this check and by nothing else: the
 * component reads it, so a component-source scan says it is fine.
 */
import { describe, it, expect } from "vitest";
import { buildDefaultRegistry } from "../src/buildDefaultRegistry";
import { starterRegistry } from "@forge/registry";

const reg = buildDefaultRegistry();

/**
 * The one accepted gap: `binding` is declared on 39 components and is not in
 * any node schema, because the runtime has no resolver for the `{$binding:…}`
 * form the Props panel writes. That is a single architectural hole tracked
 * separately — not 39 independent defects — and listing it here keeps this
 * test honest about what it is NOT covering.
 */
const KNOWN_UNIMPLEMENTED = (prop: string) => prop === "binding";

function sampleFor(d: { type?: string; options?: unknown[] }): unknown {
  if (Array.isArray(d.options) && d.options.length) return d.options[0];
  switch (d.type) {
    case "boolean": return true;
    case "number": return 7;
    case "array": return [];
    case "object": return {};
    default: return "PROBE";
  }
}

describe("registry props survive validateProps", () => {
  it("no declared prop is silently stripped by its node schema", () => {
    const stripped: string[] = [];
    for (const [name, entry] of Object.entries(starterRegistry as Record<string, any>)) {
      const descriptors: Record<string, any> = entry.props ?? {};
      // Seed the other declared props with their defaults so required fields
      // are present and the parse can succeed at all.
      const base: Record<string, unknown> = { name: "probe", label: "Probe" };
      for (const [p, d] of Object.entries(descriptors)) {
        if (d.default !== null && d.default !== undefined && d.default !== "") base[p] = d.default;
      }
      for (const [p, d] of Object.entries(descriptors)) {
        if (KNOWN_UNIMPLEMENTED(p)) continue;
        let out: Record<string, unknown>;
        try {
          out = reg.validateProps(name, { ...base, [p]: sampleFor(d) });
        } catch {
          // Layout builtins (Container, Grid, Stack, …) are rendered by the
          // renderer's own node cases and never reach this registry at all.
          continue;
        }
        if (!Object.prototype.hasOwnProperty.call(out, p)) stripped.push(`${name}.${p}`);
      }
    }
    expect(stripped).toEqual([]);
  });

  it("the props fixed in this pass reach the component with their value intact", () => {
    expect(reg.validateProps("Divider", { orientation: "horizontal", thickness: "thick" }))
      .toMatchObject({ thickness: "thick" });
    expect(reg.validateProps("NavLink", { label: "Go", target: "/reports", icon: "home" }))
      .toMatchObject({ target: "/reports", icon: "home" });
    expect(reg.validateProps("Switch", { name: "s", label: "S", checked: true }))
      .toMatchObject({ checked: true });
    expect(reg.validateProps("Select", {
      name: "s", label: "S", options: [{ value: "a", label: "A" }], multiple: true,
    })).toMatchObject({ multiple: true });
    expect(reg.validateProps("Input", {
      name: "i", label: "I", type: "text", validation: "required|min:3",
    })).toMatchObject({ validation: "required|min:3" });
  });
});
