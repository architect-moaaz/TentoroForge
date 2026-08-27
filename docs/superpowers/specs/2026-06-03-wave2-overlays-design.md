# Missing Components — Wave 2: Overlay & Menu Family — Design Spec

**Date:** 2026-06-03
**Status:** Approved-by-program (Wave 2 of the "implement all missing components" program; continuous execution)
**Reference:** deep-research missing-components audit + the component-addition recipe (traced from Checkbox, applied in Wave 1).

---

## 1. Goal

Add 7 trigger-anchored overlay components, **fully wired** so the AI generator can emit them and the renderer renders them:

**DropdownMenu, Popover, Tooltip, Drawer (Sheet), ContextMenu, HoverCard, Menubar.**

## 2. Key decision — build on Radix (matches existing `Dialog`)

The library already depends on Radix (`@radix-ui/react-dialog` powers `Dialog`; `@radix-ui/react-dropdown-menu`, `-select`, `-checkbox`, `-toast`, `cmdk` are installed). Hand-rolling positioning/portal/focus-trap/collision for 7 overlays would be error-prone and inconsistent with `Dialog`. **Therefore Wave 2 components wrap Radix primitives.**

Dependencies to add to `packages/library/package.json` (Radix versions matching the existing `^1`/`^2` line): `@radix-ui/react-popover`, `@radix-ui/react-tooltip`, `@radix-ui/react-context-menu`, `@radix-ui/react-hover-card`, `@radix-ui/react-menubar`. Already present: `@radix-ui/react-dropdown-menu` (DropdownMenu), `@radix-ui/react-dialog` (Drawer/Sheet).

## 3. Schema modeling (generator-friendly, data-driven)

Overlays have a trigger + floating content. To keep them emittable by the LLM generator (which works best with flat data props), each is modeled as a **leaf node with data props**, not arbitrary children:

- **DropdownMenu** — `{ trigger: string, triggerIcon?: string, items: { label: string; value: string; icon?: string; disabled?: boolean }[], align?: "start"|"center"|"end" }`. Renders a trigger button + a Radix menu of items; selecting an item dispatches its `value` (via the standard `onSelect`/binding).
- **ContextMenu** — `{ label: string, items: {...same as DropdownMenu} }`. `label` is the right-clickable surface text; items appear on right-click.
- **Menubar** — `{ menus: { label: string; items: { label: string; value: string }[] }[] }`. A horizontal bar of menus.
- **Tooltip** — `{ label: string, content: string, side?: "top"|"right"|"bottom"|"left" }`. `label` = trigger text; `content` = hover hint.
- **HoverCard** — `{ label: string, title?: string, content: string }`. Richer hover preview.
- **Popover** — `{ trigger: string, title?: string, content: string, align?: "start"|"center"|"end" }`. Click-triggered floating panel.
- **Drawer** (Sheet) — `{ id: string, title?: string, side?: "left"|"right"|"top"|"bottom", description?: string, content: string }`. Side-anchored overlay; opened like `Dialog` (a Button's `opensDialog` targets `id`); reuses the `DialogStateContext` open/close mechanism so it integrates with the existing trigger pattern.

Each component also accepts `style?: StyleSlotT`, `className?`, and where interactive an `onSelect?`/`__on*` test hook.

## 4. The per-component recipe (same as Wave 1)

For each `<Name>`: `packages/library/src/components/<Name>/<Name>.{tsx,schema.ts}` (the `.tsx` wraps the Radix primitive, `"use client"`, StyleSlot passthrough on the trigger root, `data-<name>`); a strict node in **`packages/schema/src/nodes/overlay.ts`** (new file, imported into `page.ts` and added to the `NodeV2` union); a `starterRegistry` entry (category `"navigation"` for menus, `"feedback"` for tooltip/hovercard, `"layout"`/`"feedback"` for drawer/popover); index exports; vitest tests. Renderer needs no change (LibraryDispatcher).

## 5. Testing

Radix portals content into `document.body`; @testing-library/react can drive triggers and assert content:
- **DropdownMenu/ContextMenu/Menubar:** open via trigger (click / right-click / menu click), assert items render, select an item → `onSelect` fires with the item value.
- **Popover:** click trigger → content appears; click outside → closes.
- **Tooltip/HoverCard:** assert the trigger renders with correct aria; (hover-delay timing is Radix-internal — test trigger presence + that content is wired, using `open` controlled prop where needed to avoid flaky timers).
- **Drawer:** open via `DialogStateContext` (controlled `open`) → content + correct `side` data attribute render.
- **Wave verification:** add the 5 new Radix deps, `npm install`, build `packages/{library,schema,registry}` (tsc — only ensure the 7 new components + edited shared files are clean, ignoring the pre-existing `dialogEntry "container"` error), run the library + schema suites, assert `starterRegistry` lists all 7.

## 6. Risks

- **New dependencies** — adds 5 `@radix-ui/*` packages (small, tree-shakeable, same family as existing deps). Run `npm install` before building.
- **SSR / renderer** — Radix overlays are client components (`"use client"`); the schema renderer already handles `"use client"` library nodes (Dialog does). Content is portal-rendered, which is fine for the platform's client preview.
- **Schema data-modeling vs children** — modeling menu items as a data array (not child nodes) keeps generation simple but means menu items can't be arbitrary nodes; acceptable for v1 (matches how the generator emits Select/MultiSelect options).
- **Test flakiness on hover** — prefer controlled `open` props in tests over real hover timers for Tooltip/HoverCard.
