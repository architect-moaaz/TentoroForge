/**
 * IR-to-AHTML Converter
 *
 * Converts AppIR (JSON IR) → Annotated HTML pages.
 * Each PageIR becomes an HTML document with Tailwind classes and
 * data-* annotations encoding logic (bindings, actions, state, slots).
 */

import type { AppIR, PageIR, IRNode, DataSourceDef } from "@tentoroforge/ir";
import type { AnnotatedApp, AnnotatedPage } from "./types.js";

// Layout emitters
import { emitStackHtml, emitRowHtml, emitGridHtml, emitSpacerHtml, emitDividerHtml } from "./emitters/layout.js";
// Content emitters
import {
  emitTextHtml, emitIconHtml, emitImageHtml, emitAvatarHtml, emitBadgeHtml,
  emitTagHtml, emitButtonHtml, emitStatCardHtml, emitEmptyStateHtml, emitSkeletonHtml,
} from "./emitters/content.js";
// Input emitters
import {
  emitTextInputHtml, emitTextAreaHtml, emitSelectHtml, emitCheckboxHtml,
  emitToggleHtml, emitRadioGroupHtml, emitDatePickerHtml, emitFilePickerHtml,
  emitRichTextEditorHtml, emitSliderHtml, emitColorPickerHtml,
} from "./emitters/inputs.js";
// Composite emitters
import {
  emitDataTableHtml, emitFormHtml, emitCardHtml, emitTabsHtml,
  emitAccordionHtml, emitChartHtml, emitModalTriggerHtml,
} from "./emitters/composites.js";
// Control flow emitters
import { emitSlotHtml, emitRepeaterHtml, emitAsyncSlotHtml, emitPlaceholderSlotHtml } from "./emitters/control.js";

// ---------------------------------------------------------------------------
// Emitter registry
// ---------------------------------------------------------------------------

type HtmlEmitter = (node: any, depth: number) => string;

const EMITTERS: Record<string, HtmlEmitter> = {
  // Layout
  Stack: emitStackHtml,
  Row: emitRowHtml,
  Grid: emitGridHtml,
  Spacer: emitSpacerHtml,
  Divider: emitDividerHtml,
  // Content
  Text: emitTextHtml,
  Icon: emitIconHtml,
  Image: emitImageHtml,
  Avatar: emitAvatarHtml,
  Badge: emitBadgeHtml,
  Tag: emitTagHtml,
  Button: emitButtonHtml,
  StatCard: emitStatCardHtml,
  EmptyState: emitEmptyStateHtml,
  Skeleton: emitSkeletonHtml,
  // Input
  TextInput: emitTextInputHtml,
  TextArea: emitTextAreaHtml,
  Select: emitSelectHtml,
  Checkbox: emitCheckboxHtml,
  Toggle: emitToggleHtml,
  RadioGroup: emitRadioGroupHtml,
  DatePicker: emitDatePickerHtml,
  FilePicker: emitFilePickerHtml,
  RichTextEditor: emitRichTextEditorHtml,
  Slider: emitSliderHtml,
  ColorPicker: emitColorPickerHtml,
  // Composites
  DataTable: emitDataTableHtml,
  Form: emitFormHtml,
  Card: emitCardHtml,
  Tabs: emitTabsHtml,
  Accordion: emitAccordionHtml,
  Chart: emitChartHtml,
  ModalTrigger: emitModalTriggerHtml,
  // Control flow
  Slot: emitSlotHtml,
  Repeater: emitRepeaterHtml,
  AsyncSlot: emitAsyncSlotHtml,
  PlaceholderSlot: emitPlaceholderSlotHtml,
};

// ---------------------------------------------------------------------------
// Core dispatch function (exported for use by emitters)
// ---------------------------------------------------------------------------

export function emitNodeToHtml(node: IRNode, depth: number): string {
  if (!node || !node.node) return "";

  const emitter = EMITTERS[node.node];
  if (!emitter) {
    const pad = indent(depth);
    return `${pad}<!-- Unknown node: ${node.node} -->`;
  }

  return emitter(node, depth);
}

// ---------------------------------------------------------------------------
// Indentation helper (exported for use by emitters)
// ---------------------------------------------------------------------------

export function indent(depth: number): string {
  return "  ".repeat(depth);
}

// ---------------------------------------------------------------------------
// Page converter
// ---------------------------------------------------------------------------

function convertPage(page: PageIR, dataSources: Record<string, DataSourceDef>): AnnotatedPage {
  const bodyContent = emitNodeToHtml(page.root, 2);

  // Build page-level attributes
  const pageAttrs: string[] = [
    `data-page-id="${page.$id}"`,
    `data-route="${page.route}"`,
  ];
  if (page.title) pageAttrs.push(`data-title="${page.title}"`);
  if (page.auth?.required) {
    pageAttrs.push(`data-auth-required="true"`);
    if (page.auth.roles?.length) {
      pageAttrs.push(`data-auth-roles="${page.auth.roles.join(",")}"`);
    }
  }

  // Find which data sources this page uses (scan body for source references)
  const usedSources = findUsedSources(bodyContent, dataSources);
  const sourceMetaTags = Object.entries(usedSources)
    .map(([name, def]) => {
      const attrs = [
        `data-source="${name}"`,
        `data-source-method="${def.method}"`,
        `data-source-path="${def.path}"`,
      ];
      if (def.params) {
        attrs.push(`data-source-params='${JSON.stringify(def.params)}'`);
      }
      return `    <meta ${attrs.join(" ")} />`;
    })
    .join("\n");

  // State definitions as meta tags
  const stateMetaTags = page.state
    ? Object.entries(page.state)
        .map(([key, val]) => `    <meta data-state="${key}" data-state-value='${JSON.stringify(val)}' />`)
        .join("\n")
    : "";

  // Modal definitions
  const modalHtml = page.modals
    ? Object.entries(page.modals)
        .map(([id, modal]) => {
          const sizeAttr = modal.size ? ` data-modal-size="${modal.size}"` : "";
          const bodyHtml = emitNodeToHtml(modal.body, 3);
          const footerHtml = modal.footer ? emitNodeToHtml(modal.footer, 3) : "";
          return `    <div data-modal-id="${id}"${sizeAttr}>
      <h2 class="text-lg font-semibold">${modal.title}</h2>
${modal.description ? `      <p class="text-sm text-muted-foreground">${modal.description}</p>` : ""}
${bodyHtml}
${footerHtml}
    </div>`;
        })
        .join("\n")
    : "";

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script src="https://cdn.tailwindcss.com"></script>
${sourceMetaTags}
${stateMetaTags}
</head>
<body>
  <div ${pageAttrs.join(" ")}>
${bodyContent}
  </div>
${modalHtml}
</body>
</html>`;

  return {
    pageId: page.$id,
    route: page.route,
    title: page.title,
    auth: page.auth ? { required: page.auth.required, roles: page.auth.roles } : undefined,
    html,
    dataSources: Object.keys(usedSources).length > 0 ? usedSourcesAsBindings(usedSources) : undefined,
  };
}

// ---------------------------------------------------------------------------
// App converter — main entry point
// ---------------------------------------------------------------------------

export function irToAnnotatedHtml(appIR: AppIR): AnnotatedApp {
  const pages = appIR.pages.map((page) => convertPage(page, appIR.dataSources));

  return {
    name: appIR.app.name,
    theme: appIR.app.theme,
    dataSources: dataSourceDefsToBindings(appIR.dataSources),
    pages,
    navigation: appIR.navigation?.items.map((item) => ({
      label: item.label,
      icon: item.icon,
      route: item.route,
      children: item.children?.map((child) => ({
        label: child.label,
        icon: child.icon,
        route: child.route,
      })),
    })),
  };
}

/** Convert a single PageIR to annotated HTML (convenience) */
export function pageIrToAnnotatedHtml(
  page: PageIR,
  dataSources: Record<string, DataSourceDef> = {},
): AnnotatedPage {
  return convertPage(page, dataSources);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function findUsedSources(
  html: string,
  dataSources: Record<string, DataSourceDef>,
): Record<string, DataSourceDef> {
  const used: Record<string, DataSourceDef> = {};
  for (const [name, def] of Object.entries(dataSources)) {
    // Check if the source name appears in the HTML (in data-source, data-repeat, etc.)
    if (html.includes(`"${name}"`) || html.includes(`="${name}"`) || html.includes(`source:${name}`)) {
      used[name] = def;
    }
  }
  return used;
}

function dataSourceDefsToBindings(
  defs: Record<string, DataSourceDef>,
): Record<string, import("./types.js").DataSourceBinding> {
  const result: Record<string, import("./types.js").DataSourceBinding> = {};
  for (const [name, def] of Object.entries(defs)) {
    result[name] = {
      name,
      method: def.method,
      path: def.path,
      params: def.params as any,
    };
  }
  return result;
}

function usedSourcesAsBindings(
  used: Record<string, DataSourceDef>,
): Record<string, import("./types.js").DataSourceBinding> {
  return dataSourceDefsToBindings(used);
}
