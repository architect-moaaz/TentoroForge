import { describe, expect, it } from "vitest";
import { z } from "zod";

import { NodeV2 } from "../src/page";

/**
 * The runtime component registry and the schema's node union are built
 * independently, and they diverged: a component could be registered, appear in
 * the emitted catalog, be authored against it, pass every gate, project
 * cleanly — and then fail validation here and render as nothing, with a
 * console warning as the only trace. `AuthForm` did exactly that.
 *
 * They agree by construction now because NodeV2 ends with the open
 * `LibraryNode` fallback, the same one `Node` has always had. These tests pin
 * that property rather than a list of names, so adding a component to the
 * registry can never require remembering to add it here too.
 */
describe("NodeV2 accepts any registered component", () => {
  const node = (type: string, props: Record<string, unknown> = {}) => ({
    id: "n-0", type, props,
  });

  it("accepts a component the strict union never enumerated", () => {
    // Not in the discriminated union; only reachable via the open fallback.
    expect(NodeV2.safeParse(node("AuthForm", { mode: "signIn" })).success).toBe(true);
  });

  it("accepts a component invented after this test was written", () => {
    expect(NodeV2.safeParse(node("SomeComponentAddedLater")).success).toBe(true);
  });

  it("still enforces the strict types it does know", () => {
    // Heading is enumerated, so its own rules continue to apply.
    const bad = NodeV2.safeParse({ id: "n", type: "Heading", props: { level: 99 } });
    expect(bad.success).toBe(false);
  });

  it("is not a hole: an id is required and structural names are reserved", () => {
    expect(NodeV2.safeParse({ type: "AuthForm", props: {} }).success).toBe(false);
    // `Stack` is a reserved structural bucket; the fallback must not shadow it
    // with a loose shape.
    const stack = NodeV2.safeParse({ id: "n", type: "Stack", children: [] });
    expect(stack.success).toBe(true);
  });
});

describe("a component's props are defined once", () => {
  it("the library derives AuthForm's props from the schema node", async () => {
    const schema: any = await import("../dist/nodes/forms.js");
    const library: any = await import(
      "../../library/dist/library/src/components/AuthForm/AuthForm.schema.js"
    );
    // Same object, not two declarations that happen to look alike. Two copies
    // is how AuthForm became renderable by the registry and rejected by the
    // page schema at the same time.
    expect(library.AuthFormProps).toBe(schema.AuthFormNode.shape.props);
  });

  it("AuthForm validates as a strict node, not via the open fallback", async () => {
    const { Page }: any = await import("../dist/page.js");
    const ok = Page.safeParse({
      schemaVersion: "2", id: "P", route: "/x",
      root: { id: "n", type: "AuthForm", props: { mode: "signIn" } },
    });
    expect(ok.success).toBe(true);

    // Strict means its own rules apply: an unknown mode is refused.
    const bad = Page.safeParse({
      schemaVersion: "2", id: "P", route: "/x",
      root: { id: "n", type: "AuthForm", props: { mode: "telepathy" } },
    });
    expect(bad.success).toBe(false);
  });
});
