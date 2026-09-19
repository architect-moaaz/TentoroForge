// next/link for the editor's JIT preview: a plain anchor whose click is a
// move the editor hears about (see navigation.tsx), never a real load.
import * as React from "react";
import { __forgeGo } from "./navigation";

type Props = React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string | { pathname?: string; query?: Record<string, string> }; prefetch?: boolean; replace?: boolean; scroll?: boolean; shallow?: boolean; passHref?: boolean; legacyBehavior?: boolean };

function toHref(href: Props["href"]): string {
  if (typeof href === "string") return href;
  const q = href.query ? "?" + new URLSearchParams(href.query).toString() : "";
  return (href.pathname ?? "/") + q;
}

const Link = React.forwardRef<HTMLAnchorElement, Props>(function Link({ href, onClick, prefetch, replace, scroll, shallow, passHref, legacyBehavior, children, ...rest }, ref) {
  const url = toHref(href);
  return (
    <a ref={ref} href={url} onClick={(e) => {
      onClick?.(e);
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.button !== 0) return;
      e.preventDefault();
      if (/^https?:\/\//.test(url)) { window.open(url, "_blank", "noopener"); return; }
      __forgeGo(url, !!replace);
    }} {...rest}>{children}</a>
  );
});
export default Link;
