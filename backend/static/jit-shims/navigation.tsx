// next/navigation for the editor's JIT preview. The page runs from a blob
// URL, where the History API refuses app paths, so where the app "is" lives
// in memory and every move is reported to the editor, which decides what to
// show next (a page's own bundle, in the app-wide preview).
import * as React from "react";

declare global { interface Window { __forgeLocation?: string; __forgeParams?: Record<string, string> } }

const EVENT = "forge:locationchange";
function current(): string { return window.__forgeLocation ?? "/"; }
export function __forgeGo(url: string, replace = false) {
  window.__forgeLocation = url;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: url }));
  window.parent?.postMessage({ type: "forge-editor:navigate", payload: { path: url, replace } }, "*");
}
function post(type: string) { window.parent?.postMessage({ type: "forge-editor:" + type, payload: {} }, "*"); }

export function useRouter() {
  return React.useMemo(() => ({
    push: (url: string) => __forgeGo(url),
    replace: (url: string) => __forgeGo(url, true),
    back: () => post("navigate-back"),
    forward: () => post("navigate-forward"),
    refresh: () => { (window as any).__forgeRender?.(); },
    prefetch: () => {},
  }), []);
}
function useLocation() {
  const [loc, setLoc] = React.useState(current);
  React.useEffect(() => {
    const on = () => setLoc(current());
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return loc;
}
export function usePathname() { return useLocation().split("?")[0]; }
export function useSearchParams() { const loc = useLocation(); return new URLSearchParams(loc.split("?")[1] ?? ""); }
export function useParams<T = Record<string, string>>(): T { return (window.__forgeParams ?? {}) as T; }
export function useSelectedLayoutSegment() { return null; }
export function useSelectedLayoutSegments() { return []; }
export function redirect(url: string): never { __forgeGo(url, true); throw new Error("NEXT_REDIRECT"); }
export function permanentRedirect(url: string): never { return redirect(url); }
export function notFound(): never { throw new Error("NEXT_NOT_FOUND"); }
export const ReadonlyURLSearchParams = URLSearchParams;
