/**
 * Navigation GrapeJS blocks — Navbar, Tabs, Breadcrumb, Pagination, Sidebar
 */

import type { Editor } from "grapesjs";

export function registerNavigationBlocks(editor: Editor): void {
  const bm = editor.BlockManager;

  bm.add("navbar", {
    label: "Navbar",
    category: "Navigation",
    content: `<nav class="flex items-center justify-between border-b bg-background px-6 h-16 w-full" data-component="Navbar">
  <div class="flex items-center gap-6">
    <span class="font-bold text-lg">Logo</span>
    <div class="hidden md:flex items-center gap-4">
      <a href="#" class="text-sm font-medium text-muted-foreground hover:text-foreground" data-action="navigate" data-action-to="/">Home</a>
      <a href="#" class="text-sm font-medium text-muted-foreground hover:text-foreground" data-action="navigate" data-action-to="/about">About</a>
      <a href="#" class="text-sm font-medium text-muted-foreground hover:text-foreground" data-action="navigate" data-action-to="/contact">Contact</a>
    </div>
  </div>
  <div class="flex items-center gap-3">
    <button class="inline-flex items-center justify-center rounded-md border border-input h-9 px-4 text-sm font-medium hover:bg-accent">Login</button>
    <button class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-9 px-4 text-sm font-medium">Sign up</button>
  </div>
</nav>`,
  });

  bm.add("sidebar-nav", {
    label: "Sidebar Nav",
    category: "Navigation",
    content: `<aside class="w-60 border-r flex flex-col gap-1 p-3 h-full" data-component="Sidebar">
  <div class="px-3 py-2">
    <h2 class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Menu</h2>
  </div>
  <a href="#" class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium bg-muted" data-action="navigate" data-action-to="/">Dashboard</a>
  <a href="#" class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted" data-action="navigate" data-action-to="/users">Users</a>
  <a href="#" class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted" data-action="navigate" data-action-to="/settings">Settings</a>
  <a href="#" class="flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted" data-action="navigate" data-action-to="/reports">Reports</a>
</aside>`,
  });

  bm.add("breadcrumb", {
    label: "Breadcrumb",
    category: "Navigation",
    content: `<nav class="flex items-center gap-1 text-sm" aria-label="Breadcrumb">
  <a href="#" class="text-muted-foreground hover:text-foreground">Home</a>
  <span class="text-muted-foreground">/</span>
  <a href="#" class="text-muted-foreground hover:text-foreground">Section</a>
  <span class="text-muted-foreground">/</span>
  <span class="text-foreground font-medium">Current Page</span>
</nav>`,
  });

  bm.add("tabs", {
    label: "Tabs",
    category: "Navigation",
    content: `<div class="w-full" data-component="Tabs">
  <div class="flex border-b">
    <button class="px-4 py-2 text-sm font-medium border-b-2 border-primary text-primary">Tab 1</button>
    <button class="px-4 py-2 text-sm font-medium border-b-2 border-transparent text-muted-foreground hover:text-foreground">Tab 2</button>
    <button class="px-4 py-2 text-sm font-medium border-b-2 border-transparent text-muted-foreground hover:text-foreground">Tab 3</button>
  </div>
  <div class="pt-4">
    <p class="text-sm text-muted-foreground">Tab 1 content goes here.</p>
  </div>
</div>`,
  });

  bm.add("pagination", {
    label: "Pagination",
    category: "Navigation",
    content: `<div class="flex items-center gap-1" data-component="Pagination">
  <button class="inline-flex items-center justify-center h-9 w-9 rounded-md border text-sm hover:bg-muted disabled:opacity-50">‹</button>
  <button class="inline-flex items-center justify-center h-9 w-9 rounded-md border text-sm hover:bg-muted">1</button>
  <button class="inline-flex items-center justify-center h-9 w-9 rounded-md border bg-primary text-primary-foreground text-sm">2</button>
  <button class="inline-flex items-center justify-center h-9 w-9 rounded-md border text-sm hover:bg-muted">3</button>
  <span class="px-2 text-sm text-muted-foreground">…</span>
  <button class="inline-flex items-center justify-center h-9 w-9 rounded-md border text-sm hover:bg-muted">10</button>
  <button class="inline-flex items-center justify-center h-9 w-9 rounded-md border text-sm hover:bg-muted">›</button>
</div>`,
  });

  bm.add("steps", {
    label: "Steps / Progress",
    category: "Navigation",
    content: `<div class="flex items-center gap-0 w-full" data-component="Steps">
  <div class="flex items-center gap-2">
    <div class="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-medium">1</div>
    <span class="text-sm font-medium">Account</span>
  </div>
  <div class="flex-1 h-px bg-border mx-3"></div>
  <div class="flex items-center gap-2">
    <div class="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-medium">2</div>
    <span class="text-sm font-medium">Details</span>
  </div>
  <div class="flex-1 h-px bg-muted mx-3"></div>
  <div class="flex items-center gap-2">
    <div class="flex h-8 w-8 items-center justify-center rounded-full border text-sm font-medium text-muted-foreground">3</div>
    <span class="text-sm text-muted-foreground">Review</span>
  </div>
</div>`,
  });
}
