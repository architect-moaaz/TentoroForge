"use client";
import * as React from "react";
import DOMPurify from "dompurify";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { CustomBlockPropsType } from "./CustomBlock.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * Escape-hatch component. Renders sanitized HTML via dompurify (default
 * config: strips <script>, on* handlers, dangerous URLs). Optional
 * `tailwind` class string applied to the wrapper. `label` surfaces in
 * the editor as the block's display name.
 *
 * NOTE: dompurify requires a browser environment. The "use client"
 * directive opts this component out of RSC server rendering. For SSR
 * support see Task 21.
 *
 * Emitted classnames + data attributes:
 *
 *   <div class="custom-block {tailwind}" [data-custom-label] [data-motion]>
 *     <inner sanitized html>
 */
export interface CustomBlockProps extends CustomBlockPropsType {
  style?: StyleSlotT;
}

export function CustomBlock({ html, tailwind, label, style }: CustomBlockProps) {
  // DOMPurify requires `window`; in Next.js SSR it returns an empty string
  // which shows a blank block until hydration. Sanitize post-mount via
  // useState/useEffect so the block renders on both first paint and after
  // hydration.
  //
  // ADD_TAGS widens the allowlist for embedded media (file previews, docs).
  // Default XSS defenses still apply (scripts, on*=, javascript: URLs stay
  // stripped). ADD_ATTR carries the attributes those tags need — plus
  // `target` for links that open the file in a new tab.
  const [sanitized, setSanitized] = React.useState<string>("");
  React.useEffect(() => {
    try {
      setSanitized(
        DOMPurify.sanitize(html, {
          ADD_TAGS: ["iframe", "object", "embed"],
          ADD_ATTR: [
            "allow",
            "allowfullscreen",
            "frameborder",
            "referrerpolicy",
            "sandbox",
            "loading",
            "data",
            "type",
            "target",
          ],
        }) as unknown as string,
      );
    } catch {
      setSanitized("");
    }
  }, [html]);

  const className = ["custom-block", tailwind].filter(Boolean).join(" ");

  return (
    <div
      className={className}
      data-custom-label={label}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
      dangerouslySetInnerHTML={{ __html: sanitized }}
    />
  );
}
