import { describe, it, expect } from "vitest";
import { z } from "zod";
import { AccordionPanelNode } from "@tentoroforge/schema";
import { createRegistry, type LibraryEntry, type LibraryCategory } from "../src/registry";
import {
  Hero, HeroProps,
  FadeIn, FadeInProps,
  Stagger, StaggerProps,
  CustomBlock, CustomBlockProps,
  Skeleton, SkeletonProps,
  MetricTile, MetricTileProps,
  FeatureCard, FeatureCardProps,
  Avatar, AvatarProps,
  KeyValueList, KeyValueListProps,
  Input, InputProps,
  Select, SelectProps,
  Textarea, TextareaProps,
  Checkbox, CheckboxProps,
  DatePicker, DatePickerProps,
  Section, SectionProps,
  Split, SplitProps,
  Sidebar, SidebarProps,
  Cluster, ClusterProps,
  Tabs, TabsProps,
  Accordion, AccordionProps,
  AccordionPanel,
} from "../src/index";

/** The 21 new components added in Tasks 11-18. */
const NEW_COMPONENT_NAMES = [
  "Hero", "Section", "Split", "Sidebar", "Cluster", "Tabs",
  "Accordion", "AccordionPanel",
  "MetricTile", "FeatureCard", "Avatar", "KeyValueList",
  "Skeleton",
  "Input", "Select", "Textarea", "Checkbox", "DatePicker",
  "FadeIn", "Stagger",
  "CustomBlock",
] as const;

function buildNewComponentRegistry() {
  const reg = createRegistry();
  // Layout (v2 nodes + marketing)
  reg.register({ name: "Hero",          component: Hero,          propsSchema: HeroProps,          category: "layout",   acceptsChildren: true  });
  reg.register({ name: "Section",       component: Section,       propsSchema: SectionProps,       category: "layout",   acceptsChildren: true  });
  reg.register({ name: "Split",         component: Split,         propsSchema: SplitProps,         category: "layout",   acceptsChildren: true  });
  reg.register({ name: "Sidebar",       component: Sidebar,       propsSchema: SidebarProps,       category: "layout",   acceptsChildren: true  });
  reg.register({ name: "Cluster",       component: Cluster,       propsSchema: ClusterProps,       category: "layout",   acceptsChildren: true  });
  reg.register({ name: "Tabs",          component: Tabs,          propsSchema: TabsProps,          category: "layout",   acceptsChildren: true  });
  reg.register({ name: "Accordion",     component: Accordion,     propsSchema: AccordionProps,     category: "layout",   acceptsChildren: true  });
  reg.register({ name: "AccordionPanel",component: AccordionPanel,propsSchema: AccordionPanelNode.shape.props,                                          category: "layout", acceptsChildren: true });
  // Static
  reg.register({ name: "MetricTile",    component: MetricTile,    propsSchema: MetricTileProps,    category: "static",   acceptsChildren: false });
  reg.register({ name: "FeatureCard",   component: FeatureCard,   propsSchema: FeatureCardProps,   category: "static",   acceptsChildren: false });
  reg.register({ name: "Avatar",        component: Avatar,        propsSchema: AvatarProps,        category: "static",   acceptsChildren: false });
  reg.register({ name: "KeyValueList",  component: KeyValueList,  propsSchema: KeyValueListProps,  category: "static",   acceptsChildren: false });
  // Feedback
  reg.register({ name: "Skeleton",      component: Skeleton,      propsSchema: SkeletonProps,      category: "feedback", acceptsChildren: false });
  // Form inputs
  reg.register({ name: "Input",         component: Input,         propsSchema: InputProps,         category: "form",     acceptsChildren: false });
  reg.register({ name: "Select",        component: Select,        propsSchema: SelectProps,        category: "form",     acceptsChildren: false });
  reg.register({ name: "Textarea",      component: Textarea,      propsSchema: TextareaProps,      category: "form",     acceptsChildren: false });
  reg.register({ name: "Checkbox",      component: Checkbox,      propsSchema: CheckboxProps,      category: "form",     acceptsChildren: false });
  reg.register({ name: "DatePicker",    component: DatePicker,    propsSchema: DatePickerProps,    category: "form",     acceptsChildren: false });
  // Motion
  reg.register({ name: "FadeIn",        component: FadeIn,        propsSchema: FadeInProps,        category: "motion",   acceptsChildren: true  });
  reg.register({ name: "Stagger",       component: Stagger,       propsSchema: StaggerProps,       category: "motion",   acceptsChildren: true  });
  // Custom
  reg.register({ name: "CustomBlock",   component: CustomBlock,   propsSchema: CustomBlockProps,   category: "custom",   acceptsChildren: false });
  return reg;
}

describe("Registry", () => {
  it("registers and looks up entries by name", () => {
    const reg = createRegistry();
    const entry: LibraryEntry = {
      name: "Button",
      component: () => null,
      propsSchema: z.object({ label: z.string() }).strict(),
      category: "interactive",
      acceptsChildren: false,
    };
    reg.register(entry);
    expect(reg.get("Button")).toBe(entry);
    expect(reg.has("Button")).toBe(true);
    expect(reg.has("Unknown")).toBe(false);
  });

  it("rejects duplicate registration", () => {
    const reg = createRegistry();
    const e: LibraryEntry = {
      name: "X", component: () => null, propsSchema: z.object({}).strict(),
      category: "static", acceptsChildren: false,
    };
    reg.register(e);
    expect(() => reg.register(e)).toThrow(/already registered/);
  });

  it("validates props through entry's propsSchema", () => {
    const reg = createRegistry();
    reg.register({
      name: "Button",
      component: () => null,
      propsSchema: z.object({ label: z.string() }).strict(),
      category: "interactive",
      acceptsChildren: false,
    });
    expect(() => reg.validateProps("Button", { label: "Save" })).not.toThrow();
    expect(() => reg.validateProps("Button", { label: 1 })).toThrow();
  });

  describe("new components (Tasks 11-18)", () => {
    it("has all 21 new component names in list()", () => {
      const reg = buildNewComponentRegistry();
      const names = reg.list().map((e) => e.name);
      for (const name of NEW_COMPONENT_NAMES) {
        expect(names, `expected ${name} in registry`).toContain(name);
      }
      expect(names).toHaveLength(21);
    });

    it("has correct categories for representative new entries", () => {
      const reg = buildNewComponentRegistry();
      expect(reg.has("Hero")).toBe(true);
      expect(reg.get("Hero")?.category).toBe("layout");
      expect(reg.get("FadeIn")?.category).toBe("motion");
      expect(reg.get("Stagger")?.category).toBe("motion");
      expect(reg.get("CustomBlock")?.category).toBe("custom");
      expect(reg.get("Skeleton")?.category).toBe("feedback");
    });

    it("accepts LibraryCategory type values 'motion' and 'custom' without type errors", () => {
      // TypeScript-level: if LibraryCategory didn't include these, the register
      // calls above would fail tsc. This runtime check confirms the values are used.
      const motionCat: LibraryCategory = "motion";
      const customCat: LibraryCategory = "custom";
      expect(motionCat).toBe("motion");
      expect(customCat).toBe("custom");
    });

    it("AccordionPanel is registered as layout with acceptsChildren=true", () => {
      const reg = buildNewComponentRegistry();
      const entry = reg.get("AccordionPanel");
      expect(entry).toBeDefined();
      expect(entry?.category).toBe("layout");
      expect(entry?.acceptsChildren).toBe(true);
    });
  });
});
