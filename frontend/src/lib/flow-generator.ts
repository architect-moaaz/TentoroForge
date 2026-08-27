/**
 * Flow Auto-Generator — creates navigation flow graph from IR pages.
 *
 * Analyzes IR page structure (entity list/detail/create patterns)
 * and generates screen nodes + edges for the navigation editor.
 */

import type { ScreenNodeSerialized, NavEdgeSerialized, NavLink } from "@/types/navigation";

interface IRPage {
  $id: string;
  route: string;
  title?: string;
  root?: { node: string; [key: string]: unknown };
}

interface IRNavItem {
  label: string;
  icon?: string;
  route: string;
}

interface AppIR {
  pages: IRPage[];
  navigation?: { items: IRNavItem[] };
  app?: { name?: string };
}

interface GeneratedFlow {
  screens: ScreenNodeSerialized[];
  edges: NavEdgeSerialized[];
  sidebarLinks: NavLink[];
  defaultScreen: string | null;
}

// Layout constants
const COL_WIDTH = 280;
const ROW_HEIGHT = 140;
const START_X = 80;
const START_Y = 80;

/**
 * Generate a complete navigation flow from IR pages.
 *
 * Groups pages by entity (list/detail/create), creates screen nodes
 * with auto-layout positions, and connects them with appropriate edges.
 */
export function generateFlowFromIR(ir: AppIR): GeneratedFlow {
  const pages = ir.pages || [];
  const navItems = ir.navigation?.items || [];

  // Classify pages
  const loginPage = pages.find((p) => p.route === "/login");
  const signupPage = pages.find((p) => p.route === "/signup");
  const dashboardPage = pages.find((p) => p.route === "/dashboard" || p.$id === "dashboard");

  // Group entity pages: /trucks, /trucks/[id], /trucks/new
  const entityGroups = new Map<string, { list?: IRPage; detail?: IRPage; create?: IRPage }>();
  const specialPages: IRPage[] = [];

  for (const page of pages) {
    if (["/login", "/signup", "/dashboard"].includes(page.route) || page.$id === "dashboard") continue;

    // Match entity patterns
    const listMatch = page.route.match(/^\/([a-z-]+)$/);
    const detailMatch = page.route.match(/^\/([a-z-]+)\/\[.+\]$/);
    const createMatch = page.route.match(/^\/([a-z-]+)\/new$/);

    if (listMatch) {
      const entity = listMatch[1];
      if (!entityGroups.has(entity)) entityGroups.set(entity, {});
      entityGroups.get(entity)!.list = page;
    } else if (detailMatch) {
      const entity = detailMatch[1];
      if (!entityGroups.has(entity)) entityGroups.set(entity, {});
      entityGroups.get(entity)!.detail = page;
    } else if (createMatch) {
      const entity = createMatch[1];
      if (!entityGroups.has(entity)) entityGroups.set(entity, {});
      entityGroups.get(entity)!.create = page;
    } else {
      specialPages.push(page);
    }
  }

  const screens: ScreenNodeSerialized[] = [];
  const edges: NavEdgeSerialized[] = [];
  const sidebarLinks: NavLink[] = [];
  let edgeId = 0;

  // --- Auth pages (top row) ---
  let col = 0;
  if (loginPage) {
    screens.push(makeScreen(loginPage, START_X + col * COL_WIDTH, START_Y, { layout: "blank" }));
    col++;
  }
  if (signupPage) {
    screens.push(makeScreen(signupPage, START_X + col * COL_WIDTH, START_Y, { layout: "blank" }));
    // Login ↔ Signup
    if (loginPage) {
      edges.push(makeEdge(`e-${edgeId++}`, loginPage.$id, signupPage.$id, "Sign up", "link"));
      edges.push(makeEdge(`e-${edgeId++}`, signupPage.$id, loginPage.$id, "Sign in", "link"));
    }
    col++;
  }

  // --- Dashboard (second row, center) ---
  const dashX = START_X + Math.floor(entityGroups.size / 2) * COL_WIDTH;
  const dashY = START_Y + ROW_HEIGHT;

  if (dashboardPage) {
    screens.push(makeScreen(dashboardPage, dashX, dashY, { isDefault: true, layout: "sidebar" }));
    // Login → Dashboard
    if (loginPage) {
      edges.push(makeEdge(`e-${edgeId++}`, loginPage.$id, dashboardPage.$id, "auth success", "redirect"));
    }
    sidebarLinks.push({ id: `nav-dashboard`, label: "Dashboard", route: "/dashboard", icon: "layout-dashboard", order: 0 });
  }

  // --- Entity groups (third row) ---
  let entityCol = 0;
  let linkOrder = 1;
  for (const [entity, group] of entityGroups) {
    const baseX = START_X + entityCol * COL_WIDTH;
    const baseY = START_Y + ROW_HEIGHT * 2;
    const label = formatLabel(entity);

    // List page
    if (group.list) {
      screens.push(makeScreen(group.list, baseX, baseY, { layout: "sidebar" }));
      // Dashboard → List
      if (dashboardPage) {
        edges.push(makeEdge(`e-${edgeId++}`, dashboardPage.$id, group.list.$id, label, "link"));
      }
      // Sidebar link
      sidebarLinks.push({
        id: `nav-${entity}`,
        label,
        route: group.list.route,
        icon: navItems.find((n) => n.route === group.list!.route)?.icon || "list",
        order: linkOrder++,
      });
    }

    // Detail page (below list)
    if (group.detail) {
      screens.push(makeScreen(group.detail, baseX, baseY + ROW_HEIGHT, { layout: "sidebar" }));
      // List → Detail (row click)
      if (group.list) {
        edges.push(makeEdge(`e-${edgeId++}`, group.list.$id, group.detail.$id, "row click", "link"));
      }
    }

    // Create page (below-right of list)
    if (group.create) {
      screens.push(makeScreen(group.create, baseX + COL_WIDTH * 0.6, baseY + ROW_HEIGHT, { layout: "sidebar" }));
      // List → Create (new button)
      if (group.list) {
        edges.push(makeEdge(`e-${edgeId++}`, group.list.$id, group.create.$id, "new button", "link"));
      }
      // Create → List (submit success)
      if (group.list) {
        edges.push(makeEdge(`e-${edgeId++}`, group.create.$id, group.list.$id, "submit", "redirect"));
      }
    }

    entityCol++;
  }

  // --- Special pages ---
  for (let i = 0; i < specialPages.length; i++) {
    const page = specialPages[i];
    screens.push(makeScreen(page, START_X + (entityGroups.size + i) * COL_WIDTH, START_Y + ROW_HEIGHT * 2, { layout: "sidebar" }));
    if (dashboardPage) {
      edges.push(makeEdge(`e-${edgeId++}`, dashboardPage.$id, page.$id, page.title || page.$id, "link"));
    }
    sidebarLinks.push({
      id: `nav-${page.$id}`,
      label: page.title || formatLabel(page.$id),
      route: page.route,
      icon: "file",
      order: linkOrder++,
    });
  }

  return {
    screens,
    edges,
    sidebarLinks,
    defaultScreen: dashboardPage?.$id || screens[0]?.id || null,
  };
}

/**
 * Convert flow back to IR navigation actions.
 *
 * Reads the edges and generates the navigate actions that should be
 * wired into IR nodes (buttons, table rows, forms).
 */
export function flowToIRActions(
  edges: NavEdgeSerialized[],
  screens: ScreenNodeSerialized[],
): FlowAction[] {
  const screenMap = new Map(screens.map((s) => [s.id, s]));
  const actions: FlowAction[] = [];

  for (const edge of edges) {
    const source = screenMap.get(edge.source);
    const target = screenMap.get(edge.target);
    if (!source || !target) continue;

    const label = edge.data?.label || "";
    const navType = edge.data?.navType || "link";
    const targetRoute = target.data.route;

    actions.push({
      sourceRoute: source.data.route,
      targetRoute,
      trigger: inferTrigger(label),
      navType,
      label,
    });
  }

  return actions;
}

export interface FlowAction {
  sourceRoute: string;
  targetRoute: string;
  trigger: "button_click" | "row_click" | "form_submit" | "auto_redirect" | "link";
  navType: string;
  label: string;
}

// --- Helpers ---

function makeScreen(
  page: IRPage,
  x: number,
  y: number,
  extra?: Partial<ScreenNodeSerialized["data"]>,
): ScreenNodeSerialized {
  return {
    id: page.$id,
    type: "screen",
    position: { x, y },
    data: {
      label: page.title || formatLabel(page.$id),
      route: page.route,
      pageId: page.$id,
      ...extra,
    },
  };
}

function makeEdge(
  id: string,
  source: string,
  target: string,
  label: string,
  navType: "link" | "redirect" | "back",
): NavEdgeSerialized {
  return {
    id,
    source,
    target,
    data: { label, navType },
  };
}

function formatLabel(slug: string): string {
  return slug
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function inferTrigger(label: string): FlowAction["trigger"] {
  const l = label.toLowerCase();
  if (l.includes("row") || l.includes("click")) return "row_click";
  if (l.includes("submit") || l.includes("form")) return "form_submit";
  if (l.includes("redirect") || l.includes("auth") || l.includes("success")) return "auto_redirect";
  if (l.includes("button") || l.includes("new") || l.includes("add")) return "button_click";
  return "link";
}
