/**
 * Central emit dispatcher — routes each IRNode to its type-specific emitter.
 */

import type { IRNode } from "@tentoroforge/ir";
import { EmitContext } from "./context.js";

// Layout
import { emitStack, emitRow, emitGrid, emitSpacer, emitDivider } from "./emitters/layout.js";
// Content
import {
  emitText, emitIcon, emitImage, emitAvatar, emitBadge, emitTag,
  emitButton, emitStatCard, emitEmptyState, emitSkeleton,
} from "./emitters/content.js";
// Inputs
import {
  emitTextInput, emitTextArea, emitSelect, emitCheckbox, emitToggle,
  emitRadioGroup, emitDatePicker, emitFilePicker, emitRichTextEditor,
  emitSlider, emitColorPicker,
} from "./emitters/inputs.js";
// Control flow
import { emitSlot, emitRepeater, emitAsyncSlot } from "./emitters/control.js";
// Composites
import {
  emitDataTable, emitForm, emitCard, emitTabs,
  emitAccordion, emitChart, emitModalTrigger,
} from "./emitters/composites.js";

// ---------------------------------------------------------------------------
// Emitter registry
// ---------------------------------------------------------------------------

type NodeEmitter = (node: any, ctx: EmitContext) => string;

const EMITTERS: Record<string, NodeEmitter> = {
  // Layout
  Stack: emitStack,
  Row: emitRow,
  Grid: emitGrid,
  Spacer: emitSpacer,
  Divider: emitDivider,
  // Content
  Text: emitText,
  Icon: emitIcon,
  Image: emitImage,
  Avatar: emitAvatar,
  Badge: emitBadge,
  Tag: emitTag,
  Button: emitButton,
  StatCard: emitStatCard,
  EmptyState: emitEmptyState,
  Skeleton: emitSkeleton,
  // Inputs
  TextInput: emitTextInput,
  TextArea: emitTextArea,
  Select: emitSelect,
  Checkbox: emitCheckbox,
  Toggle: emitToggle,
  RadioGroup: emitRadioGroup,
  DatePicker: emitDatePicker,
  FilePicker: emitFilePicker,
  RichTextEditor: emitRichTextEditor,
  Slider: emitSlider,
  ColorPicker: emitColorPicker,
  // Control flow
  Slot: emitSlot,
  Repeater: emitRepeater,
  AsyncSlot: emitAsyncSlot,
  // Composites
  DataTable: emitDataTable,
  Form: emitForm,
  Card: emitCard,
  Tabs: emitTabs,
  Accordion: emitAccordion,
  Chart: emitChart,
  ModalTrigger: emitModalTrigger,
  // Escape hatch
  Custom: emitCustom,
  // Fragment reference (should be resolved before emit)
  FragmentRef: emitFragmentRef,
};

// ---------------------------------------------------------------------------
// Main dispatch
// ---------------------------------------------------------------------------

export function emitNode(node: IRNode, ctx: EmitContext): string {
  const nodeType = (node as { node: string }).node;
  const emitter = EMITTERS[nodeType];

  if (!emitter) {
    return `{/* Unknown node type: ${nodeType} */}`;
  }

  // Handle visibility wrapper
  const visible = (node as { visible?: string }).visible;
  let jsx: string;
  if (visible) {
    const inner = emitter(node, ctx);
    const condition = visible.startsWith("state:") || visible.startsWith("source:")
      ? visible.replace("state:", "").replace(/source:(\w+)/, "$1Data")
      : visible;
    jsx = `{${condition} && (\n${inner}\n)}`;
  } else {
    jsx = emitter(node, ctx);
  }

  // Wrap with boundary comments in devMode (for round-trip parser)
  if (ctx.devMode && ctx.currentPath.length > 0) {
    const pathStr = ctx.currentPath.join(".");
    return `{/* @ir-node: ${pathStr} */}\n${jsx}\n{/* @ir-end: ${pathStr} */}`;
  }

  return jsx;
}

// ---------------------------------------------------------------------------
// Custom node emitter
// ---------------------------------------------------------------------------

function emitCustom(node: { code: string; imports?: string[] }, ctx: EmitContext): string {
  if (node.imports) {
    for (const imp of node.imports) {
      // Simple: assume default import of package name
      ctx.ensureImport(imp, imp);
    }
  }
  return `{(() => {\n${node.code}\n})()}`;
}

// ---------------------------------------------------------------------------
// Fragment ref (should already be resolved)
// ---------------------------------------------------------------------------

function emitFragmentRef(node: { $ref: string }, _ctx: EmitContext): string {
  return `{/* Unresolved fragment ref: ${node.$ref} */}`;
}
