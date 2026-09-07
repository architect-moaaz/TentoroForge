"use client";
import { useContext } from "react";
import { WorkflowDispatcherContext, tokenToCssVar, useNavigator } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

type Props = {
  label: string;
  navigate: string;
  workflow?: string;
  args?: Record<string, unknown>;
  /** Where to open the destination. "_blank" also gets a safe `rel`. */
  target?: "_self" | "_blank";
  style?: StyleSlotT;
  /** Schema-authored utility classes. When present the class is authoritative
   * for the link's look: the default underline/color inline styles are dropped
   * so `bg-*`/`text-*`/`no-underline` classes can style it as a button. */
  className?: string;
  /** Test injection only — allows bypassing context in unit tests. */
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
};

/** An app-relative route the Navigator should handle, as opposed to an external
 *  URL, a mail/tel scheme, or a bare fragment the browser resolves itself. */
function isInternalRoute(dest: string): boolean {
  return dest.startsWith("/") && !dest.startsWith("//");
}

export function Link({ label, navigate, workflow, args, target, style, className, __dispatch }: Props) {
  const ctxDispatch = useContext(WorkflowDispatcherContext);
  const nav = useNavigator();
  const dest = typeof navigate === "string" ? navigate.trim() : "";
  const href = (u: string) => (nav.resolveHref ? nav.resolveHref(u) : u);

  // A LINK WITH NOWHERE TO GO IS NOT A LINK.
  //
  // The registry seeds `navigate: ""`, which rendered `<a href="">` — an anchor
  // that is focusable, blue, underlined, `cursor: pointer`, and reloads the
  // current page when clicked. The user's report was exactly that: "a control
  // styled as a working link that is inert". `href=""` is worse than no href,
  // because an anchor WITHOUT href is not a link to any assistive technology
  // and does not invite the click in the first place.
  //
  // A `workflow` with no `navigate` is still a real control, so it keeps its
  // interactive rendering — only the "no destination and no behaviour at all"
  // case is marked unset.
  const inert = !dest && !workflow;

  const onClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (workflow) {
      const dispatch = __dispatch ?? ctxDispatch;
      if (dispatch) dispatch(workflow, args);
    }
    // Route internal links through the Navigator (soft nav + routed modals).
    // Keep the <a href> for accessibility / new-tab / crawlers, but hijack the
    // plain left-click. Modifier clicks, an explicit _blank target, and
    // external URLs fall through to the browser's default so open-in-new-tab
    // still works.
    if (
      isInternalRoute(dest) &&
      target !== "_blank" &&
      !e.defaultPrevented &&
      e.button === 0 &&
      !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey
    ) {
      e.preventDefault();
      nav.push(dest);
    }
  };

  const defaultLook = className
    ? {}
    : {
        // An unset link is rendered as the plain text it behaves like, so its
        // look matches what it does.
        color: inert ? "inherit" : `var(${tokenToCssVar("primary.500")})`,
        textDecoration: inert ? ("none" as const) : ("underline" as const),
        fontSize: `var(${tokenToCssVar("typography.base")})`,
      };
  // The href below is the RESOLVED url, not the raw route. onClick hijacks a
  // plain left-click and goes through nav.push, but middle-click,
  // modifier-click, "copy link address", a crawler and the whole pre-hydration
  // window all read the attribute — and under a base path it pointed at the
  // origin root. Same translation as push, from the same seam, so the two can
  // never disagree.
  return (
    <a
      // No `href` at all when there is nothing to go to — see above.
      {...(inert ? {} : { href: dest ? href(dest) : undefined })}
      {...(inert ? { "data-link-unset": "", "aria-disabled": true } : {})}
      {...(target === "_blank"
        ? { target: "_blank", rel: "noopener noreferrer" }
        : target
          ? { target }
          : {})}
      onClick={inert ? undefined : onClick}
      className={className}
      style={{
        ...defaultLook,
        cursor: inert ? "default" : "pointer",
        ...resolveStyle(style),
      }}
      {...useMotion(style?.motion)}
    >
      {label}
    </a>
  );
}
