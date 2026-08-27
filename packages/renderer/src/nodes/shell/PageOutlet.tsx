import { useContext } from "react";
import { PageOutletContext } from "../../runtime/page-outlet-context";

/**
 * PageOutlet renders the page content injected via PageOutletContext.
 * Place this node inside a shell schema where the page body should appear.
 * If no context value is set (i.e. the schema is rendered standalone,
 * without a shell wrapping provider), it returns null silently.
 *
 * Wraps the content in a padded container so per-page schemas don't
 * render edge-to-edge against the shell chrome. Padding scales with
 * viewport (mobile is tighter to maximise content area, desktop has
 * comfortable breathing room).
 *
 * The node accepts a `props.padding` override (e.g. "tight" | "comfortable"
 * | "loose" | "none") so individual layouts can opt out of the default
 * when they want a full-bleed marketing hero or a docs-style narrow column.
 */
const PADDING_BY_DENSITY: Record<string, string> = {
  none:        "",
  tight:       "px-4 py-4 sm:px-6 sm:py-6",
  comfortable: "px-4 py-6 sm:px-6 sm:py-8 lg:px-8",
  loose:       "px-6 py-8 sm:px-10 sm:py-12 lg:px-16",
};

export function PageOutlet({ node }: { node?: { props?: { padding?: string } } } = {}) {
  const content = useContext(PageOutletContext);
  const density = node?.props?.padding ?? "comfortable";
  const padClass = PADDING_BY_DENSITY[density] ?? PADDING_BY_DENSITY.comfortable;

  // No content in context (shell-only preview in the editor, or unbound
  // route): render a centered placeholder card so the user understands what
  // this region represents instead of staring at a huge empty area below
  // the header.
  if (content === null || content === undefined) {
    return (
      <div className={`${padClass} flex items-center justify-center min-h-[calc(100vh-64px)]`}>
        <div className="border border-dashed rounded-lg p-12 text-center max-w-md text-muted-foreground">
          <div className="text-sm font-medium">Page content area</div>
          <div className="text-xs mt-2">
            When a user navigates to a route inside the shell, their page schema renders here.
          </div>
        </div>
      </div>
    );
  }

  if (!padClass) return <>{content}</>;
  return <div className={padClass}>{content}</div>;
}
