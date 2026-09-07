// Five golden fixtures covering common app shapes. The DOM produced by
// the engine for each must be structurally identical under JIT + SSR.

export const minimalText = {
  schema: {
    schemaVersion: "2" as const,
    id: "min",
    root: { type: "Text", id: "t1", props: { content: "Hello, world" } },
  },
  designSpec: { register: "default" },
};

export const buttonList = {
  schema: {
    schemaVersion: "2" as const,
    id: "btns",
    root: {
      type: "Stack", id: "s1", props: { gap: "md" },
      children: [
        { type: "Button", id: "b1", props: { label: "Primary", variant: "primary" } },
        { type: "Button", id: "b2", props: { label: "Secondary", variant: "secondary" } },
      ],
    },
  },
  designSpec: { register: "default" },
};

export const headingPlusText = {
  schema: {
    schemaVersion: "2" as const,
    id: "h",
    root: {
      type: "Stack", id: "s",
      children: [
        { type: "Heading", id: "h1", props: { content: "About us", level: "1" } },
        { type: "Text", id: "t1", props: { content: "We build editors" } },
      ],
    },
  },
  designSpec: { register: "default" },
};

export const cardLayout = {
  schema: {
    schemaVersion: "2" as const,
    id: "c",
    root: {
      type: "Card", id: "card1",
      children: [
        { type: "Heading", id: "ch", props: { content: "Card title", level: "2" } },
        { type: "Text", id: "ct", props: { content: "Card body" } },
      ],
    },
  },
  designSpec: { register: "default" },
};

export const previewBoundText = {
  schema: {
    schemaVersion: "2" as const,
    id: "p",
    root: { type: "Text", id: "t",
            props: { content: "Hello, {{user.name}}" } },
  },
  designSpec: { register: "default" },
  previewData: { user: { name: "Alex" } },
};

export const GOLDEN_FIXTURES = {
  minimalText, buttonList, headingPlusText, cardLayout, previewBoundText,
};
