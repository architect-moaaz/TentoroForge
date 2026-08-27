// ---------------------------------------------------------------------------
// Screen Node (for React Flow navigation diagram)
// ---------------------------------------------------------------------------

export interface ScreenNode {
  id: string;
  name: string;
  route: string;
  pageId?: string; // linked page_definition
  isDefault?: boolean;
  isError?: boolean;
  layout?: "sidebar" | "topnav" | "blank";
}

export interface ScreenNodeData extends Record<string, unknown> {
  label: string;
  route: string;
  pageId?: string;
  isDefault?: boolean;
  isError?: boolean;
  layout?: "sidebar" | "topnav" | "blank";
}

export interface ScreenNodeSerialized {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: ScreenNodeData;
}

export interface NavEdgeSerialized {
  id: string;
  source: string;
  target: string;
  data?: NavEdgeData;
}

export interface NavEdgeData extends Record<string, unknown> {
  label?: string;
  navType?: "link" | "redirect" | "back";
}

// ---------------------------------------------------------------------------
// Navigation Config
// ---------------------------------------------------------------------------

export interface NavLink {
  id: string;
  label: string;
  route: string;
  icon?: string;
  parentId?: string | null;
  order: number;
  visibleToRoles?: string[];
}

export interface NavigationConfig {
  id: string;
  projectId: string;
  screens: ScreenNodeSerialized[];
  edges: NavEdgeSerialized[];
  sidebarLinks: NavLink[];
  topbarLinks: NavLink[];
  defaultScreen?: string;
  errorScreen?: string;
}

// ---------------------------------------------------------------------------
// Module System
// ---------------------------------------------------------------------------

export interface AppModule {
  id: string;
  name: string;
  description?: string;
  color?: string;
  screens: string[]; // screen node IDs
  createdAt: string;
}

export interface ModuleDependencyEdge {
  id: string;
  sourceModuleId: string;
  targetModuleId: string;
  dependencyType: "imports" | "navigates" | "shares_data";
}

// ---------------------------------------------------------------------------
// Navigation Editor State
// ---------------------------------------------------------------------------

export interface NavEditorState {
  screens: ScreenNodeSerialized[];
  edges: NavEdgeSerialized[];
  sidebarLinks: NavLink[];
  topbarLinks: NavLink[];
  modules: AppModule[];
  moduleDependencies: ModuleDependencyEdge[];
  defaultScreen?: string;
  errorScreen?: string;
}
