"use client";

import React from "react";
import type { IRNode, NodePath, NodeRendererProps } from "./types";

// Layout
import { StackRenderer, RowRenderer, GridRenderer, SpacerRenderer, DividerRenderer } from "./nodes/layout";
// Content
import { TextRenderer, IconRenderer, ImageRenderer, AvatarRenderer, BadgeRenderer, TagRenderer, ButtonRenderer, StatCardRenderer, EmptyStateRenderer, SkeletonRenderer } from "./nodes/content";
// Inputs
import { TextInputRenderer, TextAreaRenderer, SelectRenderer, CheckboxRenderer, ToggleRenderer, RadioGroupRenderer, DatePickerRenderer, FilePickerRenderer, SliderRenderer, ColorPickerRenderer, RichTextEditorRenderer } from "./nodes/inputs";
// Composites
import { DataTableRenderer, FormRenderer, CardRenderer, TabsRenderer, AccordionRenderer, ModalTriggerRenderer, ChartRenderer } from "./nodes/composites";
// Control flow
import { SlotRenderer, RepeaterRenderer, AsyncSlotRenderer } from "./nodes/control";

type RendererComponent = React.ComponentType<NodeRendererProps>;

const NODE_REGISTRY: Record<string, RendererComponent> = {
  // Layout
  Stack: StackRenderer,
  Row: RowRenderer,
  Grid: GridRenderer,
  Spacer: SpacerRenderer,
  Divider: DividerRenderer,

  // Content
  Text: TextRenderer,
  Icon: IconRenderer,
  Image: ImageRenderer,
  Avatar: AvatarRenderer,
  Badge: BadgeRenderer,
  Tag: TagRenderer,
  Button: ButtonRenderer,
  StatCard: StatCardRenderer,
  EmptyState: EmptyStateRenderer,
  Skeleton: SkeletonRenderer,

  // Inputs
  TextInput: TextInputRenderer,
  TextArea: TextAreaRenderer,
  Select: SelectRenderer,
  Checkbox: CheckboxRenderer,
  Toggle: ToggleRenderer,
  RadioGroup: RadioGroupRenderer,
  DatePicker: DatePickerRenderer,
  FilePicker: FilePickerRenderer,
  Slider: SliderRenderer,
  ColorPicker: ColorPickerRenderer,
  RichTextEditor: RichTextEditorRenderer,

  // Composites
  DataTable: DataTableRenderer,
  Form: FormRenderer,
  Card: CardRenderer,
  Tabs: TabsRenderer,
  Accordion: AccordionRenderer,
  ModalTrigger: ModalTriggerRenderer,
  Chart: ChartRenderer,

  // Control flow
  Slot: SlotRenderer,
  Repeater: RepeaterRenderer,
  AsyncSlot: AsyncSlotRenderer,
};

export function RenderNode({ node, path }: { node: IRNode; path: NodePath }) {
  if (!node || !node.node) return null;

  const Component = NODE_REGISTRY[node.node];

  if (!Component) {
    return (
      <div
        data-ir-path={path.join(".")}
        className="border border-dashed border-amber-300 bg-amber-50 rounded p-2 text-xs text-amber-700"
      >
        Unknown node: <code>{node.node}</code>
      </div>
    );
  }

  return <Component node={node} path={path} />;
}
