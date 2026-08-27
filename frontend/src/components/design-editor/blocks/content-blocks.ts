/**
 * Content GrapeJS blocks — Text, Button, Image, Badge, StatCard, etc.
 */

import type { Editor } from "grapesjs";

export function registerContentBlocks(editor: Editor): void {
  const bm = editor.BlockManager;

  bm.add("heading-1", {
    label: "Heading 1",
    category: "Content",
    content: '<h1 class="text-2xl font-bold tracking-tight">Heading</h1>',
  });

  bm.add("heading-2", {
    label: "Heading 2",
    category: "Content",
    content: '<h2 class="text-xl font-semibold tracking-tight">Heading</h2>',
  });

  bm.add("paragraph", {
    label: "Paragraph",
    category: "Content",
    content: '<p class="text-sm">Paragraph text goes here.</p>',
  });

  bm.add("caption", {
    label: "Caption",
    category: "Content",
    content: '<span class="text-xs text-muted-foreground">Caption text</span>',
  });

  bm.add("button-primary", {
    label: "Button (Primary)",
    category: "Content",
    content: '<button class="inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2" data-action="navigate" data-action-to="/">Button</button>',
  });

  bm.add("button-secondary", {
    label: "Button (Secondary)",
    category: "Content",
    content: '<button class="inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 h-10 px-4 py-2" data-action="navigate" data-action-to="/">Button</button>',
  });

  bm.add("button-outline", {
    label: "Button (Outline)",
    category: "Content",
    content: '<button class="inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium border border-input bg-background hover:bg-accent h-10 px-4 py-2" data-action="navigate" data-action-to="/">Button</button>',
  });

  bm.add("image", {
    label: "Image",
    category: "Content",
    content: '<img src="https://placehold.co/400x200" alt="Placeholder" class="rounded-md object-cover" />',
  });

  bm.add("badge", {
    label: "Badge",
    category: "Content",
    content: '<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-secondary text-secondary-foreground">Badge</span>',
  });

  bm.add("stat-card", {
    label: "Stat Card",
    category: "Content",
    content: `<div class="rounded-lg border bg-card p-6" data-component="StatCard">
      <div class="flex items-center justify-between">
        <span class="text-sm text-muted-foreground">Total Users</span>
      </div>
      <div class="mt-2 text-2xl font-bold">1,234</div>
      <span class="text-xs text-muted-foreground">+12% from last month</span>
    </div>`,
  });

  bm.add("empty-state", {
    label: "Empty State",
    category: "Content",
    content: `<div class="flex flex-col items-center justify-center py-12 text-center gap-3" data-component="EmptyState">
      <h3 class="text-lg font-medium">No items yet</h3>
      <p class="text-sm text-muted-foreground">Get started by creating your first item.</p>
      <button class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 py-2 text-sm font-medium">Create Item</button>
    </div>`,
  });

  bm.add("card", {
    label: "Card",
    category: "Content",
    content: `<div class="rounded-lg border bg-card" data-component="Card">
      <div class="p-4">
        <h3 class="font-semibold">Card Title</h3>
        <p class="text-sm text-muted-foreground mt-1">Card description goes here.</p>
      </div>
    </div>`,
  });

  bm.add("card-with-header", {
    label: "Card (Header + Footer)",
    category: "Content",
    content: `<div class="rounded-lg border bg-card" data-component="Card">
      <div class="px-4 py-3 border-b">
        <h3 class="font-semibold">Card Title</h3>
        <p class="text-xs text-muted-foreground">Card subtitle</p>
      </div>
      <div class="p-4">
        <p class="text-sm text-muted-foreground">Card content goes here.</p>
      </div>
      <div class="px-4 py-3 border-t flex items-center justify-end gap-2">
        <button class="inline-flex items-center justify-center rounded-md border h-8 px-3 text-xs font-medium hover:bg-accent">Cancel</button>
        <button class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-8 px-3 text-xs font-medium">Confirm</button>
      </div>
    </div>`,
  });

  // Alerts
  bm.add("alert-info", {
    label: "Alert (Info)",
    category: "Content",
    content: `<div class="flex gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4" role="alert">
      <svg class="h-4 w-4 text-blue-600 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
      <div class="text-sm">
        <p class="font-medium text-blue-800">Information</p>
        <p class="text-blue-700 mt-0.5">This is an informational message.</p>
      </div>
    </div>`,
  });

  bm.add("alert-success", {
    label: "Alert (Success)",
    category: "Content",
    content: `<div class="flex gap-3 rounded-lg border border-green-200 bg-green-50 p-4" role="alert">
      <svg class="h-4 w-4 text-green-600 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
      <div class="text-sm">
        <p class="font-medium text-green-800">Success</p>
        <p class="text-green-700 mt-0.5">Your action was completed successfully.</p>
      </div>
    </div>`,
  });

  bm.add("alert-warning", {
    label: "Alert (Warning)",
    category: "Content",
    content: `<div class="flex gap-3 rounded-lg border border-yellow-200 bg-yellow-50 p-4" role="alert">
      <svg class="h-4 w-4 text-yellow-600 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4M12 17h.01"/></svg>
      <div class="text-sm">
        <p class="font-medium text-yellow-800">Warning</p>
        <p class="text-yellow-700 mt-0.5">Please review this before continuing.</p>
      </div>
    </div>`,
  });

  bm.add("alert-error", {
    label: "Alert (Error)",
    category: "Content",
    content: `<div class="flex gap-3 rounded-lg border border-red-200 bg-red-50 p-4" role="alert">
      <svg class="h-4 w-4 text-red-600 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
      <div class="text-sm">
        <p class="font-medium text-red-800">Error</p>
        <p class="text-red-700 mt-0.5">Something went wrong. Please try again.</p>
      </div>
    </div>`,
  });

  // Avatar
  bm.add("avatar", {
    label: "Avatar",
    category: "Content",
    content: `<div class="flex items-center gap-3">
      <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted font-medium text-sm">JD</div>
      <div>
        <p class="text-sm font-medium">John Doe</p>
        <p class="text-xs text-muted-foreground">john@example.com</p>
      </div>
    </div>`,
  });

  bm.add("avatar-group", {
    label: "Avatar Group",
    category: "Content",
    content: `<div class="flex items-center">
      <div class="flex h-8 w-8 items-center justify-center rounded-full border-2 border-background bg-blue-500 text-white text-xs font-medium">A</div>
      <div class="flex h-8 w-8 -ml-2 items-center justify-center rounded-full border-2 border-background bg-green-500 text-white text-xs font-medium">B</div>
      <div class="flex h-8 w-8 -ml-2 items-center justify-center rounded-full border-2 border-background bg-purple-500 text-white text-xs font-medium">C</div>
      <div class="flex h-8 w-8 -ml-2 items-center justify-center rounded-full border-2 border-background bg-muted text-xs font-medium text-muted-foreground">+5</div>
    </div>`,
  });

  // Progress
  bm.add("progress-bar", {
    label: "Progress Bar",
    category: "Content",
    content: `<div class="space-y-1.5">
      <div class="flex items-center justify-between text-sm">
        <span class="font-medium">Progress</span>
        <span class="text-muted-foreground">65%</span>
      </div>
      <div class="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div class="h-full w-[65%] rounded-full bg-primary transition-all"></div>
      </div>
    </div>`,
  });

  // List
  bm.add("list-unordered", {
    label: "List (Bullet)",
    category: "Content",
    content: `<ul class="space-y-1 text-sm list-none">
      <li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-primary shrink-0"></span>List item one</li>
      <li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-primary shrink-0"></span>List item two</li>
      <li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-primary shrink-0"></span>List item three</li>
    </ul>`,
  });

  bm.add("list-ordered", {
    label: "List (Numbered)",
    category: "Content",
    content: `<ol class="space-y-1 text-sm list-none">
      <li class="flex items-center gap-2"><span class="h-5 w-5 rounded-full bg-muted text-xs flex items-center justify-center font-medium shrink-0">1</span>First step</li>
      <li class="flex items-center gap-2"><span class="h-5 w-5 rounded-full bg-muted text-xs flex items-center justify-center font-medium shrink-0">2</span>Second step</li>
      <li class="flex items-center gap-2"><span class="h-5 w-5 rounded-full bg-muted text-xs flex items-center justify-center font-medium shrink-0">3</span>Third step</li>
    </ol>`,
  });

  // Accordion
  bm.add("accordion", {
    label: "Accordion",
    category: "Content",
    content: `<div class="divide-y rounded-lg border" data-component="Accordion">
      <div>
        <button class="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50">
          Section 1
          <svg class="h-4 w-4 text-muted-foreground" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <div class="px-4 pb-3 text-sm text-muted-foreground">Content for section 1.</div>
      </div>
      <div>
        <button class="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50">
          Section 2
          <svg class="h-4 w-4 text-muted-foreground" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>
        </button>
      </div>
      <div>
        <button class="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50">
          Section 3
          <svg class="h-4 w-4 text-muted-foreground" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>
        </button>
      </div>
    </div>`,
  });

  // Table
  bm.add("table-static", {
    label: "Table (Static)",
    category: "Content",
    content: `<div class="w-full overflow-auto rounded-lg border">
      <table class="w-full text-sm">
        <thead class="border-b bg-muted/50">
          <tr>
            <th class="text-left px-4 py-2.5 font-medium text-muted-foreground">Name</th>
            <th class="text-left px-4 py-2.5 font-medium text-muted-foreground">Status</th>
            <th class="text-left px-4 py-2.5 font-medium text-muted-foreground">Date</th>
            <th class="text-right px-4 py-2.5 font-medium text-muted-foreground">Amount</th>
          </tr>
        </thead>
        <tbody class="divide-y">
          <tr class="hover:bg-muted/30 transition-colors">
            <td class="px-4 py-3">Alice Johnson</td>
            <td class="px-4 py-3"><span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800">Active</span></td>
            <td class="px-4 py-3 text-muted-foreground">Jan 15, 2024</td>
            <td class="px-4 py-3 text-right">$1,200</td>
          </tr>
          <tr class="hover:bg-muted/30 transition-colors">
            <td class="px-4 py-3">Bob Smith</td>
            <td class="px-4 py-3"><span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800">Pending</span></td>
            <td class="px-4 py-3 text-muted-foreground">Jan 20, 2024</td>
            <td class="px-4 py-3 text-right">$850</td>
          </tr>
        </tbody>
      </table>
    </div>`,
  });

  // Link
  bm.add("link", {
    label: "Link",
    category: "Content",
    content: '<a href="#" class="text-sm text-primary underline-offset-4 hover:underline" data-action="navigate" data-action-to="/">Click here</a>',
  });

  // Skeleton loader
  bm.add("skeleton", {
    label: "Skeleton Loader",
    category: "Content",
    content: `<div class="space-y-3">
      <div class="h-4 w-3/4 rounded-md bg-muted animate-pulse"></div>
      <div class="h-4 w-full rounded-md bg-muted animate-pulse"></div>
      <div class="h-4 w-2/3 rounded-md bg-muted animate-pulse"></div>
    </div>`,
  });
}
