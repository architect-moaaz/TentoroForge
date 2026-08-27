import { describe, it, expect } from "vitest";
import { AvatarNode, KeyValueListNode, SkeletonNode } from "../../src/nodes/display";

describe("AvatarNode", () => {
  it("accepts explicit name + size", () => {
    const r = AvatarNode.parse({
      id: "a", type: "Avatar",
      props: { name: "Jane Doe", size: "md", status: "online" },
    });
    expect(r.props.size).toBe("md");
  });

  it("accepts empty props — name defaults to 'User', size to 'md'", () => {
    const r = AvatarNode.parse({ type: "Avatar", props: {} });
    expect(r.props.name).toBe("User");
    expect(r.props.size).toBe("md");
  });

  it("accepts {type:'Avatar',props:{src:'...'}} with no name or size", () => {
    const r = AvatarNode.safeParse({
      type: "Avatar",
      props: { src: "https://example.com/avatar.jpg" },
    });
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.props.name).toBe("User");
      expect(r.data.props.size).toBe("md");
    }
  });

  it("passes unknown props through (no .strict())", () => {
    // LLM-emitted schemas may include extra keys; they should not cause rejection
    const r = AvatarNode.safeParse({
      type: "Avatar",
      props: { name: "Jane", size: "sm", unknownProp: "ignored" },
    });
    expect(r.success).toBe(true);
  });
});

describe("KeyValueListNode", () => {
  it("items required, each label+value", () => {
    const r = KeyValueListNode.parse({
      id: "k", type: "KeyValueList",
      props: { items: [
        { label: "Email", value: "x@y.com", copyable: true },
        { label: "Role",  value: "Admin" },
      ]},
    });
    expect(r.props.items.length).toBe(2);
    expect(r.props.items[0].copyable).toBe(true);
    expect(r.props.items[1].copyable).toBeUndefined();
  });
});

describe("SkeletonNode", () => {
  it("variant + optional lines", () => {
    expect(SkeletonNode.parse({ id: "s", type: "Skeleton",
      props: { variant: "rect" } }).props.variant).toBe("rect");
    expect(SkeletonNode.parse({ id: "s", type: "Skeleton",
      props: { variant: "text", lines: 3 } }).props.lines).toBe(3);
  });

  it("SkeletonNode rejects lines when variant is not 'text'", () => {
    expect(() => SkeletonNode.parse({
      id: "s", type: "Skeleton",
      props: { variant: "rect", lines: 3 },
    })).toThrow();
    // text variant with lines is valid
    const r = SkeletonNode.parse({
      id: "s", type: "Skeleton",
      props: { variant: "text", lines: 3 },
    });
    expect(r.props.lines).toBe(3);
  });

  it("SkeletonNode rejects non-integer lines", () => {
    expect(() => SkeletonNode.parse({
      id: "s", type: "Skeleton",
      props: { variant: "text", lines: 1.5 },
    })).toThrow();
  });
});

// v2 tests (updated after softening AvatarNode to remove .strict() and add defaults)
describe("display strict mode", () => {
  it("AvatarNode passes through unknown props (no .strict())", () => {
    // Unknown props used to throw; now they are silently allowed so LLM-generated
    // schemas with extra keys still render instead of showing "invalid props".
    const r = AvatarNode.safeParse({
      id: "a", type: "Avatar",
      props: { name: "X", size: "md", whoops: "extra" },
    });
    expect(r.success).toBe(true);
  });

  it("AvatarNode rejects invalid size enum", () => {
    expect(() => AvatarNode.parse({
      id: "a", type: "Avatar",
      props: { name: "X", size: "huge" },
    })).toThrow();
  });

  it("AvatarNode treats empty name as '' (min(1) removed — defaults applied only when name is absent)", () => {
    // After softening: name has .default("User"), but when an explicit empty
    // string is passed it goes through as-is (default only fires when the key
    // is missing). The Avatar component is responsible for graceful empty-name
    // rendering. This test documents the current post-softening behaviour.
    const r = AvatarNode.safeParse({
      id: "a", type: "Avatar",
      props: { name: "", size: "md" },
    });
    // Empty string passes — min(1) was removed as part of the softening.
    expect(r.success).toBe(true);
  });

  it("KeyValueListNode rejects empty items array", () => {
    expect(() => KeyValueListNode.parse({
      id: "k", type: "KeyValueList",
      props: { items: [] },
    })).toThrow();
  });

  it("KeyValueListNode rejects empty label but accepts empty value", () => {
    expect(() => KeyValueListNode.parse({
      id: "k", type: "KeyValueList",
      props: { items: [{ label: "", value: "x" }] },
    })).toThrow();
    // empty value is allowed (renderer handles empty-state)
    const r = KeyValueListNode.parse({
      id: "k", type: "KeyValueList",
      props: { items: [{ label: "Email", value: "" }] },
    });
    expect(r.props.items[0].value).toBe("");
  });

  it("SkeletonNode rejects invalid variant", () => {
    expect(() => SkeletonNode.parse({
      id: "s", type: "Skeleton",
      props: { variant: "blob" },
    })).toThrow();
  });

  it("SkeletonNode rejects non-positive lines", () => {
    expect(() => SkeletonNode.parse({
      id: "s", type: "Skeleton",
      props: { variant: "text", lines: 0 },
    })).toThrow();
    expect(() => SkeletonNode.parse({
      id: "s", type: "Skeleton",
      props: { variant: "text", lines: -1 },
    })).toThrow();
  });

  it("AvatarNode rejects empty id", () => {
    expect(() => AvatarNode.parse({
      id: "", type: "Avatar", props: { name: "X", size: "md" },
    })).toThrow();
  });

  it("AvatarNode accepts a non-empty src", () => {
    const r = AvatarNode.parse({
      id: "a", type: "Avatar",
      props: { name: "Jane", size: "md", src: "/uploads/jane.png" },
    });
    expect(r.props.src).toBe("/uploads/jane.png");
  });

  it("AvatarNode rejects empty src string", () => {
    expect(() => AvatarNode.parse({
      id: "a", type: "Avatar",
      props: { name: "Jane", size: "md", src: "" },
    })).toThrow();
  });
});

describe("AvatarNode photoUrl", () => {
  it("accepts photoUrl prop", () => {
    const r = AvatarNode.safeParse({
      id: "a", type: "Avatar",
      props: { name: "Jane Doe", size: "md", photoUrl: "https://example.com/x.jpg" },
    });
    expect(r.success).toBe(true);
  });

  it("photoUrl is optional", () => {
    const r = AvatarNode.safeParse({
      id: "a", type: "Avatar",
      props: { name: "Jane Doe", size: "md" },
    });
    expect(r.success).toBe(true);
  });

  it("photoUrl must be a string when set (not a number)", () => {
    const r = AvatarNode.safeParse({
      id: "a", type: "Avatar",
      props: { name: "Jane Doe", size: "md", photoUrl: 123 },
    });
    expect(r.success).toBe(false);
  });
});
