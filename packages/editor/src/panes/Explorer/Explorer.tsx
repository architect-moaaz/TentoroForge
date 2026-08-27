import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { useShallow } from "zustand/react/shallow";
import {
  ChevronRight, ChevronDown, Folder, FolderOpen, FileText,
  List as ListIcon, Eye, FilePlus,
} from "lucide-react";
import type { EditorStoreApi } from "../../state/store";
import { selectOpenPaths } from "../../state/selectors";
import { usePageList, useSchemaList } from "./usePageList";

type TreeLeaf = { __leaf: string };
type TreeFolder = { [key: string]: TreeLeaf | TreeFolder };

function buildTree(paths: string[]): TreeFolder {
  const root: TreeFolder = {};
  for (const p of paths) {
    const parts = p.split("/");
    let cursor: TreeFolder = root;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!cursor[parts[i]]) cursor[parts[i]] = {} as TreeFolder;
      cursor = cursor[parts[i]] as TreeFolder;
    }
    cursor[parts[parts.length - 1]] = { __leaf: p };
  }
  return root;
}

const PAGE_TYPE_ICON: Record<string, typeof FileText> = {
  list:    ListIcon,
  detail:  Eye,
  form:    FilePlus,
};
function pageTypeIcon(name: string) {
  return PAGE_TYPE_ICON[name] ?? FileText;
}

function FolderRow({
  name,
  open,
  onToggle,
  depth,
}: {
  name: string;
  open: boolean;
  onToggle: () => void;
  depth: number;
}) {
  const Icon = open ? FolderOpen : Folder;
  const Chev = open ? ChevronDown : ChevronRight;
  return (
    <button
      type="button"
      onClick={onToggle}
      className="group flex w-full items-center gap-1.5 px-2 py-1 text-left text-xs font-medium text-muted-foreground hover:bg-muted/60 hover:text-foreground transition-colors"
      style={{ paddingLeft: 8 + depth * 12 }}
    >
      <Chev className="h-3.5 w-3.5 shrink-0" />
      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/80 group-hover:text-foreground/80" />
      <span className="truncate capitalize">{name.replace(/-/g, " ")}</span>
    </button>
  );
}

function LeafRow({
  name,
  fullPath,
  isOpen,
  depth,
  onClick,
}: {
  name: string;
  fullPath: string;
  isOpen: boolean;
  depth: number;
  onClick: () => void;
}) {
  const Icon = pageTypeIcon(name);
  const activeCls = isOpen
    ? "bg-primary/10 text-primary font-medium border-l-2 border-primary"
    : "text-foreground/80 hover:bg-muted/60 hover:text-foreground border-l-2 border-transparent";
  return (
    <button
      type="button"
      onClick={onClick}
      data-leaf={fullPath}
      data-open={isOpen ? "true" : "false"}
      className={`flex w-full items-center gap-1.5 py-1 pr-2 text-left text-xs transition-colors ${activeCls}`}
      style={{ paddingLeft: 8 + depth * 12 }}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 opacity-70" />
      <span className="truncate">{name}</span>
    </button>
  );
}

function TreeNode({
  tree,
  depth,
  onOpenPage,
  openPaths,
  expanded,
  setExpanded,
  ancestorKey,
}: {
  tree: TreeFolder;
  depth: number;
  onOpenPage: (path: string) => void;
  openPaths: string[];
  expanded: Set<string>;
  setExpanded: (s: Set<string>) => void;
  ancestorKey: string;
}): React.ReactElement {
  return (
    <div>
      {Object.entries(tree).map(([name, child]) => {
        const leafVal = (child as TreeLeaf).__leaf;
        if (leafVal !== undefined) {
          return (
            <LeafRow
              key={leafVal}
              name={name}
              fullPath={leafVal}
              depth={depth}
              isOpen={openPaths.includes(leafVal)}
              onClick={() => onOpenPage(leafVal)}
            />
          );
        }
        const folderKey = ancestorKey ? `${ancestorKey}/${name}` : name;
        const isExpanded = expanded.has(folderKey);
        const toggle = () => {
          const next = new Set(expanded);
          if (next.has(folderKey)) next.delete(folderKey);
          else next.add(folderKey);
          setExpanded(next);
        };
        return (
          <div key={folderKey}>
            <FolderRow name={name} open={isExpanded} onToggle={toggle} depth={depth} />
            {isExpanded && (
              <TreeNode
                tree={child as TreeFolder}
                depth={depth + 1}
                onOpenPage={onOpenPage}
                openPaths={openPaths}
                expanded={expanded}
                setExpanded={setExpanded}
                ancestorKey={folderKey}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function FlatRouteRow({
  route,
  pageType,
  slug,
  isOpen,
  onClick,
}: {
  route: string;
  pageType: string;
  slug: string;
  isOpen: boolean;
  onClick: () => void;
}) {
  const Icon = pageTypeIcon(pageType);
  const activeCls = isOpen
    ? "bg-primary/10 text-primary font-medium border-l-2 border-primary"
    : "text-foreground/80 hover:bg-muted/60 hover:text-foreground border-l-2 border-transparent";
  return (
    <button
      type="button"
      onClick={onClick}
      data-leaf={slug}
      data-open={isOpen ? "true" : "false"}
      className={`flex w-full items-center gap-1.5 py-1 pl-2 pr-2 text-left text-xs transition-colors ${activeCls}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 opacity-70" />
      <code className="truncate font-mono">{route}</code>
      <span className="ml-auto text-[10px] uppercase tracking-wide text-muted-foreground/80">
        {pageType}
      </span>
    </button>
  );
}

export function Explorer({
  store,
  apiBaseUrl,
  onOpenPage,
}: {
  store: EditorStoreApi;
  apiBaseUrl: string;
  onOpenPage: (path: string) => void;
}): React.ReactElement {
  // Primary: flat schema listing keyed by route. Falls back to the legacy
  // tree built from `/pages` if the new endpoint isn't available (older
  // backend, or fetch error). `_layouts/` always uses the tree since they
  // aren't pages.
  const schemaEntries = useSchemaList(apiBaseUrl);
  const allPaths = usePageList(apiBaseUrl);
  const openPaths = useStore(store, useShallow((s) => selectOpenPaths(s)));

  const layoutPaths = allPaths.filter((p) => p.startsWith("_layouts/"));
  const pagePaths = allPaths.filter((p) => !p.startsWith("_layouts/"));

  // Fallback tree when the flat endpoint isn't available.
  const pageTree: TreeFolder = buildTree(pagePaths);
  const layoutTree: TreeFolder = buildTree(layoutPaths.map((p) => p.slice("_layouts/".length)));

  // Sorted flat list — sort by route so users see all pages in one glance.
  const sortedEntries = (schemaEntries ?? []).slice().sort((a, b) =>
    a.route.localeCompare(b.route),
  );

  // Folders expand by default. Newly-discovered top-level folders (after the
  // page-list fetch resolves) get auto-expanded on first sight; user toggles
  // override that for subsequent renders.
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [layoutExpanded, setLayoutExpanded] = useState<Set<string>>(() => new Set());
  const [seenFolders, setSeenFolders] = useState<Set<string>>(() => new Set());
  useEffect(() => {
    const topLevelKeys = Object.keys(pageTree);
    const layoutKeys = Object.keys(layoutTree);
    const newPage = topLevelKeys.filter((k) => !seenFolders.has(`p/${k}`));
    const newLayout = layoutKeys.filter((k) => !seenFolders.has(`l/${k}`));
    if (newPage.length === 0 && newLayout.length === 0) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      for (const k of newPage) next.add(k);
      return next;
    });
    setLayoutExpanded((prev) => {
      const next = new Set(prev);
      for (const k of newLayout) next.add(k);
      return next;
    });
    setSeenFolders((prev) => {
      const next = new Set(prev);
      for (const k of newPage) next.add(`p/${k}`);
      for (const k of newLayout) next.add(`l/${k}`);
      return next;
    });
    // pageTree/layoutTree identity changes whenever paths update; the
    // seenFolders guard keeps user-collapsed folders from auto-reopening.
  }, [pageTree, layoutTree, seenFolders]);

  // Header is rendered by the parent (Editor.tsx) so the column header chrome
  // matches the Components header and the section is collapsible from there.
  return (
    <div className="flex flex-col">
      <div className="py-1.5">
        {schemaEntries !== null ? (
          // Flat sorted list — one row per schema, keyed by route.
          <div data-explorer-mode="flat">
            {sortedEntries.map((e) => (
              <FlatRouteRow
                key={e.slug}
                route={e.route}
                pageType={e.page_type}
                slug={e.slug}
                isOpen={openPaths.includes(e.slug)}
                onClick={() => onOpenPage(e.slug)}
              />
            ))}
          </div>
        ) : (
          // Legacy fallback: tree view from `/pages`.
          <TreeNode
            tree={pageTree}
            depth={0}
            onOpenPage={onOpenPage}
            openPaths={openPaths}
            expanded={expanded}
            setExpanded={setExpanded}
            ancestorKey=""
          />
        )}
      </div>

      {layoutPaths.length > 0 && (
        <>
          <div
            data-section="layouts"
            className="border-y border-gray-100 bg-muted/20 px-4 py-2"
          >
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Layouts
            </span>
          </div>
          <div className="py-1.5">
            <TreeNode
              tree={layoutTree}
              depth={0}
              onOpenPage={(name) => onOpenPage(`_layouts/${name}`)}
              openPaths={openPaths}
              expanded={layoutExpanded}
              setExpanded={setLayoutExpanded}
              ancestorKey=""
            />
          </div>
        </>
      )}
    </div>
  );
}
