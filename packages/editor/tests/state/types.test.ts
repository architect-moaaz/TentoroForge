import { describe, it, expect } from "vitest";
import type { EditorState, Mutation, Selection, NodeId, ValidationError } from "../../src/state/types";

describe("state/types", () => {
  it("exports the key types as a contract", () => {
    // type-only test — if this file compiles, the types exist with the right names
    const _id: NodeId = "abc";
    const _sel: Selection = [];
    const _err: ValidationError = { path: ["root"], message: "bad" };
    expect(_id).toBe("abc");
  });
});
