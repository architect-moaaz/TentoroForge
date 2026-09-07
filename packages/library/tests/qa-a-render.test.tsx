/**
 * QA audit (Agent A, feedback batch) — throwaway probe, not a real test.
 * Renders each of the 21 feedback components with the EXACT props the editor
 * seeds on drop (starterRegistry default -> normalizeSeed -> validateProps),
 * plus a marker child where the registry says the component takes children,
 * and reports what DOM comes out.
 */
import { describe, it } from "vitest";
import * as React from "react";
import { render } from "@testing-library/react";
import { starterRegistry } from "../../registry/src/starter";

const NAMES = ["Alert","AutoFocus","Banner","Drawer","EmptyState","EmptyStateRich","FocusRing","FocusTrap","HoverCard","IllustratedEmpty","InspectorPanel","LoadingState","OptimisticProvider","Popover","PresenceIndicator","Progress","Skeleton","Spinner","Tooltip","TourOverlay","UndoManager"];

const NUM = /^-?\d+(?:\.\d+)?$/;
function normalizeSeed(d: any, v: unknown) {
  if (v === undefined || v === null) return undefined;
  const numeric = d?.type === "number" || (d?.type === "enum" && Array.isArray(d.options) && d.options.length > 0 && d.options.every((o: any) => typeof o === "number" || (typeof o === "string" && NUM.test(o))));
  if (numeric && typeof v === "string" && NUM.test(v.trim())) return Number(v);
  if (d?.control === "image" && d?.imageShape === "url" && v === "") return undefined;
  return v;
}
function defaultPropsFor(name: string) {
  const e = (starterRegistry as any)[name];
  if (!e) return {};
  return Object.fromEntries(Object.entries(e.props as any).map(([k, d]: any) => [k, normalizeSeed(d, d.default)]).filter(([, v]) => v !== undefined));
}

describe("qa-a feedback render probe", () => {
  it("reports DOM for every component with registry defaults", { timeout: 120000 }, async () => {
    const lines: string[] = [];
    for (const name of NAMES) {
      const entry = (starterRegistry as any)[name];
      const slot = entry?.slots?.type;
      const props: any = defaultPropsFor(name);
      let Comp: any;
      try {
        const mod = await import(`../src/components/${name}/${name}.tsx`);
        Comp = mod[name];
      } catch (e: any) {
        lines.push(`${name.padEnd(20)} IMPORT-FAIL ${e.message}`);
        continue;
      }
      const takesChildren = slot === "list" || slot === "single";
      const child = takesChildren
        ? React.createElement("button", { "data-qa-child": "1", type: "button" }, "QA CHILD")
        : null;
      try {
        const { container, unmount } = render(React.createElement(Comp, props, child));
        const html = container.innerHTML;
        const childSeen = !!document.querySelector("[data-qa-child]");
        lines.push(
          `${name.padEnd(20)} slots=${String(slot).padEnd(6)} htmlLen=${String(html.length).padEnd(6)} ` +
          `rootEls=${container.childElementCount} text="${(container.textContent || "").trim().replace(/\s+/g, " ").slice(0, 50)}"` +
          (takesChildren ? ` CHILD_RENDERED=${childSeen}` : "") +
          (html.length === 0 ? "   <<< RENDERS NOTHING" : "")
        );
        unmount();
      } catch (e: any) {
        lines.push(`${name.padEnd(20)} THROW ${String(e.message).slice(0, 120)}`);
      }
    }
    console.log("\n===== QA-A RENDER PROBE =====\n" + lines.join("\n") + "\n=============================\n");
  });
});
