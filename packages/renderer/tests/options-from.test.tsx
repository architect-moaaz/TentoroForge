import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import * as React from "react";
import { renderNode, type DispatchContext } from "../src/runtime/dispatch";

// Minimal registry whose Select renders each option as `value|label;` and
// echoes whether `optionsFrom` leaked through to validated props — so we can
// assert both the expansion result AND that the helper field was stripped.
function makeCtx(data: Record<string, unknown>): DispatchContext {
  const registry = {
    has: (t: string) => t === "Select",
    get: () => ({ component: undefined, propsSchema: undefined }),
    validateProps: (_t: string, props: any) => props,
  };
  const Select = (props: any) =>
    React.createElement(
      "div",
      {
        "data-has-optionsfrom": props.optionsFrom ? "yes" : "no",
        "data-options": (props.options ?? [])
          .map((o: any) => `${o.value}|${o.label}`)
          .join(";"),
      },
      null
    );
  (registry.get as any) = () => ({ component: Select, propsSchema: undefined });
  return { data, registry } as any;
}

const selectNode = (extra: Record<string, unknown>) => ({
  id: "field-project",
  type: "Select",
  props: {
    name: "projectId",
    label: "Project",
    validators: { required: true },
    options: [{ value: "{{projects[0].id}}", label: "{{projects[0].name}}" }],
    ...extra,
  },
});

describe("optionsFrom — dynamic relational dropdown expansion", () => {
  it("builds one option per dataSource row, using value/label fields", () => {
    const ctx = makeCtx({
      projects: [
        { id: "uuid-a", name: "Apollo" },
        { id: "uuid-b", name: "Borealis" },
      ],
    });
    const html = renderToString(
      renderNode(selectNode({ optionsFrom: { source: "projects", value: "id", label: "name" } }) as any, ctx) as any
    );
    expect(html).toContain("data-options=\"uuid-a|Apollo;uuid-b|Borealis\"");
    // optionsFrom is stripped before reaching the component / validateProps.
    expect(html).toContain('data-has-optionsfrom="no"');
  });

  it("falls back to the static options when the source is missing/empty", () => {
    const ctx = makeCtx({ projects: [] });
    const html = renderToString(
      renderNode(selectNode({ optionsFrom: { source: "projects", value: "id", label: "name" } }) as any, ctx) as any
    );
    // Static fallback survives (the {{projects[0].id}} template renders verbatim
    // since `projects` is empty); optionsFrom still stripped.
    expect(html).toContain("{{projects[0].id}}");
    expect(html).toContain('data-has-optionsfrom="no"');
  });

  it("defaults value/label keys to id/name when omitted", () => {
    const ctx = makeCtx({ projects: [{ id: "x1", name: "Solo" }] });
    const html = renderToString(
      renderNode(selectNode({ optionsFrom: { source: "projects" } }) as any, ctx) as any
    );
    expect(html).toContain("data-options=\"x1|Solo\"");
  });

  it("uses the value as label when the label field is absent on a row", () => {
    const ctx = makeCtx({ tags: [{ id: "t1" }] });
    const html = renderToString(
      renderNode(
        {
          id: "field-tags",
          type: "Select",
          props: {
            name: "tagIds",
            label: "Tags",
            options: [{ value: "{{tags[0].id}}", label: "{{tags[0].label}}" }],
            optionsFrom: { source: "tags", value: "id", label: "label" },
          },
        } as any,
        ctx
      ) as any
    );
    expect(html).toContain("data-options=\"t1|t1\"");
  });
});
