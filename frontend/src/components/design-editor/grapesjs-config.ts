/**
 * GrapeJS Editor Configuration
 *
 * Configures the GrapeJS editor for annotated HTML editing with
 * Tailwind CSS support and custom component types.
 */

import type { Editor, EditorConfig } from "grapesjs";
import { useDesignEditorStore } from "@/stores/design-editor";

// ---------------------------------------------------------------------------
// Device presets
// ---------------------------------------------------------------------------

export const DEVICES = [
  { id: "desktop", name: "Desktop", width: "" },
  { id: "tablet", name: "Tablet", width: "768px" },
  { id: "mobile", name: "Mobile", width: "375px" },
];

// ---------------------------------------------------------------------------
// Editor configuration
// ---------------------------------------------------------------------------

export function getEditorConfig(): Partial<EditorConfig> {
  return {
    // Disable default panels — we use our own React panels
    panels: { defaults: [] },

    // Canvas configuration — Tailwind CDN + Inter font
    canvas: {
      scripts: [
        "https://cdn.tailwindcss.com",
      ],
      styles: [
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap",
      ],
    },

    // Block manager
    blockManager: {
      appendTo: undefined,
    },

    // Style manager sectors for Tailwind
    styleManager: {
      sectors: [
        {
          name: "Layout",
          open: true,
          properties: [
            { property: "display" },
            { property: "flex-direction" },
            { property: "justify-content" },
            { property: "align-items" },
            { property: "gap" },
          ],
        },
        {
          name: "Spacing",
          open: false,
          properties: [
            { property: "padding" },
            { property: "margin" },
          ],
        },
        {
          name: "Size",
          open: false,
          properties: [
            { property: "width" },
            { property: "height" },
            { property: "min-width" },
            { property: "min-height" },
          ],
        },
        {
          name: "Typography",
          open: false,
          properties: [
            { property: "font-size" },
            { property: "font-weight" },
            { property: "color" },
            { property: "text-align" },
          ],
        },
        {
          name: "Background",
          open: false,
          properties: [
            { property: "background-color" },
            { property: "background-image" },
          ],
        },
        {
          name: "Border",
          open: false,
          properties: [
            { property: "border-radius" },
            { property: "border" },
          ],
        },
      ],
    },

    // Storage — disabled (we manage saving ourselves)
    storageManager: false,

    // Layer manager
    layerManager: {
      appendTo: undefined,
    },

    // Disable default commands bar
    showToolbar: true,

    // Undoable
    undoManager: {
      trackSelection: false,
    },
  };
}

// ---------------------------------------------------------------------------
// Setup Tailwind refresh in canvas
// ---------------------------------------------------------------------------

export function setupCanvasTailwind(editor: Editor): void {
  // When canvas iframe loads, ensure Tailwind processes all classes
  editor.on("canvas:frame:load", ({ window: frameWindow }: { window: Window }) => {
    // Inject base styles for Inter font
    const style = frameWindow.document.createElement("style");
    style.textContent = `
      body { font-family: 'Inter', system-ui, sans-serif; }
      * { box-sizing: border-box; }
    `;
    frameWindow.document.head.appendChild(style);

    // Inject project theme CSS (globals.css variables) if available
    injectThemeCSS(editor);
  });

  // Also inject Tailwind config for shadcn CSS variable colors
  editor.on("canvas:frame:load", () => {
    injectTailwindConfig(editor);
  });

  // When a component is added (drag/drop), trigger Tailwind re-scan
  editor.on("component:add", () => {
    const frame = editor.Canvas.getFrameEl();
    if (frame?.contentWindow && (frame.contentWindow as any).tailwind) {
      // Force Tailwind to re-process by triggering a DOM mutation
      const body = frame.contentDocument?.body;
      if (body) {
        body.classList.add("__tw-refresh");
        requestAnimationFrame(() => body.classList.remove("__tw-refresh"));
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Theme CSS injection — makes Build & Design match Live Edit visually
// ---------------------------------------------------------------------------

/**
 * Inject the project's globals.css (CSS variables, @layer base styles)
 * into the GrapeJS canvas iframe so that Tailwind utilities like
 * `bg-primary`, `text-muted-foreground`, `border` render correctly.
 */
function injectThemeCSS(editor: Editor): void {
  const themeCSS = useDesignEditorStore.getState().themeCSS;
  if (!themeCSS) return;

  const frame = editor.Canvas.getFrameEl();
  if (!frame?.contentDocument?.head) return;

  // Remove any previously injected theme
  const existing = frame.contentDocument.getElementById("__project-theme");
  existing?.remove();

  const style = frame.contentDocument.createElement("style");
  style.id = "__project-theme";
  style.textContent = themeCSS;
  frame.contentDocument.head.appendChild(style);
}

/**
 * Inject a Tailwind CDN config so that utility classes like `bg-primary`,
 * `text-muted-foreground` resolve to `hsl(var(--primary))`, etc.
 * Without this, the CDN uses its default color palette.
 */
function injectTailwindConfig(editor: Editor): void {
  const frame = editor.Canvas.getFrameEl();
  if (!frame?.contentDocument) return;

  // Remove any previously injected config
  const existing = frame.contentDocument.getElementById("__tw-config");
  existing?.remove();

  const script = frame.contentDocument.createElement("script");
  script.id = "__tw-config";
  script.textContent = `
    if (window.tailwind) {
      tailwind.config = {
        theme: {
          extend: {
            colors: {
              border: "hsl(var(--border))",
              input: "hsl(var(--input))",
              ring: "hsl(var(--ring))",
              background: "hsl(var(--background))",
              foreground: "hsl(var(--foreground))",
              primary: {
                DEFAULT: "hsl(var(--primary))",
                foreground: "hsl(var(--primary-foreground))",
              },
              secondary: {
                DEFAULT: "hsl(var(--secondary))",
                foreground: "hsl(var(--secondary-foreground))",
              },
              destructive: {
                DEFAULT: "hsl(var(--destructive))",
                foreground: "hsl(var(--destructive-foreground))",
              },
              muted: {
                DEFAULT: "hsl(var(--muted))",
                foreground: "hsl(var(--muted-foreground))",
              },
              accent: {
                DEFAULT: "hsl(var(--accent))",
                foreground: "hsl(var(--accent-foreground))",
              },
              popover: {
                DEFAULT: "hsl(var(--popover))",
                foreground: "hsl(var(--popover-foreground))",
              },
              card: {
                DEFAULT: "hsl(var(--card))",
                foreground: "hsl(var(--card-foreground))",
              },
            },
            borderRadius: {
              lg: "var(--radius)",
              md: "calc(var(--radius) - 2px)",
              sm: "calc(var(--radius) - 4px)",
            },
          },
        },
      };
    }
  `;
  frame.contentDocument.head.appendChild(script);
}

// ---------------------------------------------------------------------------
// Register custom component types for annotated elements
// ---------------------------------------------------------------------------

export function registerCustomComponents(editor: Editor): void {
  const { Components } = editor;

  // --- Container components (droppable: true — can nest children) ---

  // Stack (vertical flex)
  Components.addType("ahtml-stack", {
    isComponent: (el) => el.getAttribute?.("data-component") === "Stack",
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          { type: "text", name: "data-component", label: "Component", value: "Stack" },
        ],
      },
    },
  });

  // Row (horizontal flex)
  Components.addType("ahtml-row", {
    isComponent: (el) => el.getAttribute?.("data-component") === "Row",
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          { type: "text", name: "data-component", label: "Component", value: "Row" },
        ],
      },
    },
  });

  // Grid
  Components.addType("ahtml-grid", {
    isComponent: (el) => el.getAttribute?.("data-component") === "Grid",
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          { type: "text", name: "data-component", label: "Component", value: "Grid" },
        ],
      },
    },
  });

  // Card component (droppable — can contain children)
  Components.addType("ahtml-card", {
    isComponent: (el) => el.getAttribute?.("data-component") === "Card",
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          { type: "text", name: "data-action", label: "Action" },
          { type: "text", name: "data-action-to", label: "Navigate To" },
        ],
      },
    },
  });

  // Form component (droppable — contains form fields)
  Components.addType("ahtml-form", {
    isComponent: (el) =>
      el.getAttribute?.("data-component") === "Form" || el.tagName === "FORM",
    model: {
      defaults: {
        tagName: "form",
        droppable: true,
        traits: [
          { type: "text", name: "data-bind", label: "State Binding" },
          {
            type: "select",
            name: "data-action",
            label: "Submit Action",
            options: [
              { id: "", name: "(none)" },
              { id: "mutate", name: "Mutate (API)" },
              { id: "trigger-workflow", name: "Trigger Workflow" },
              { id: "navigate", name: "Navigate" },
            ],
          },
          { type: "text", name: "data-action-source", label: "Action Source" },
          { type: "text", name: "data-action-workflow", label: "Workflow ID" },
        ],
      },
    },
  });

  // Tabs component (droppable — tab content areas)
  Components.addType("ahtml-tabs", {
    isComponent: (el) => el.getAttribute?.("data-component") === "Tabs",
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          { type: "text", name: "data-component-props", label: "Props (JSON)" },
        ],
      },
    },
  });

  // Slot placeholder (droppable — can be filled with content)
  Components.addType("ahtml-slot", {
    isComponent: (el) => !!el.getAttribute?.("data-slot"),
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          {
            type: "select",
            name: "data-slot",
            label: "Slot Type",
            options: [
              { id: "entity-table", name: "Entity Table" },
              { id: "entity-form", name: "Entity Form" },
              { id: "entity-detail", name: "Entity Detail" },
              { id: "stat-cards", name: "Stat Cards" },
              { id: "crud-actions", name: "CRUD Actions" },
              { id: "auth-form", name: "Auth Form" },
              { id: "search-bar", name: "Search Bar" },
              { id: "recent-items", name: "Recent Items" },
              { id: "empty-state", name: "Empty State" },
            ],
          },
          { type: "text", name: "data-entity", label: "Entity" },
        ],
      },
    },
  });

  // Repeater (droppable — template content goes inside)
  Components.addType("ahtml-repeater", {
    isComponent: (el) => !!el.getAttribute?.("data-repeat"),
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          { type: "text", name: "data-repeat", label: "Data Source" },
          { type: "text", name: "data-repeat-key", label: "Key Field" },
        ],
      },
    },
  });

  // --- Leaf components (droppable: false) ---

  // DataTable (complex component — not freely nestable)
  Components.addType("ahtml-datatable", {
    isComponent: (el) => el.getAttribute?.("data-component") === "DataTable",
    model: {
      defaults: {
        tagName: "div",
        droppable: false,
        traits: [
          { type: "text", name: "data-source", label: "Data Source" },
          { type: "text", name: "data-component-props", label: "Props (JSON)" },
        ],
      },
    },
  });

  // Button with action
  Components.addType("ahtml-button", {
    isComponent: (el) => el.tagName === "BUTTON",
    model: {
      defaults: {
        tagName: "button",
        droppable: false,
        traits: [
          {
            type: "select",
            name: "data-action",
            label: "Action",
            options: [
              { id: "", name: "(none)" },
              { id: "navigate", name: "Navigate" },
              { id: "mutate", name: "Mutate (API)" },
              { id: "openModal", name: "Open Modal" },
              { id: "setState", name: "Set State" },
              { id: "trigger-workflow", name: "Trigger Workflow" },
            ],
          },
          { type: "text", name: "data-action-to", label: "Navigate To" },
          { type: "text", name: "data-action-source", label: "Mutation Source" },
          { type: "text", name: "data-action-workflow", label: "Workflow ID" },
          { type: "text", name: "data-action-confirm", label: "Confirm Message" },
        ],
      },
    },
  });

  // Input with binding
  Components.addType("ahtml-input", {
    isComponent: (el) =>
      el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT",
    model: {
      defaults: {
        droppable: false,
        traits: [
          { type: "text", name: "data-bind", label: "State Binding" },
          { type: "text", name: "data-entity", label: "Entity" },
          { type: "text", name: "data-field", label: "Field" },
          { type: "text", name: "placeholder", label: "Placeholder" },
        ],
      },
    },
  });

  // Modal
  Components.addType("ahtml-modal", {
    isComponent: (el) => !!el.getAttribute?.("data-modal-id"),
    model: {
      defaults: {
        tagName: "div",
        droppable: true,
        traits: [
          { type: "text", name: "data-modal-id", label: "Modal ID" },
          {
            type: "select",
            name: "data-modal-size",
            label: "Size",
            options: [
              { id: "sm", name: "Small" },
              { id: "md", name: "Medium" },
              { id: "lg", name: "Large" },
              { id: "xl", name: "Extra Large" },
            ],
          },
        ],
      },
    },
  });
}
