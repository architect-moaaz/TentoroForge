"use client";
import * as React from "react";

/**
 * The one row a menu shows when it has no items.
 *
 * WHY THIS EXISTS
 * ---------------
 * Every Radix-backed menu in the library maps an `items` array into
 * `<Menu.Content>` and renders nothing else. With an empty array the portalled
 * content is still mounted, so opening it produces a **160 x 10 px white
 * sliver with `childElementCount === 0`** — a box that says nothing at all.
 * The auditor's words: "I could not tell whether it was broken or still
 * loading." That is true of a shipped app as much as of the editor canvas: a
 * menu that opens onto nothing is indistinguishable from a menu that failed.
 *
 * WHY IT IS SHARED RATHER THAN COPIED
 * -----------------------------------
 * The identical hole is in ContextMenu, DropdownMenu and every Menubar menu.
 * Three copies of the same six lines is how those three drifted apart in the
 * first place, so the note lives here once and each menu renders it behind the
 * same `items.length === 0` test.
 *
 * It is deliberately NOT a `Menu.Item`: an item is focusable and selectable,
 * and keyboard-arrowing onto "No menu items" then pressing Enter would fire a
 * selection for a row that is not one. A plain div inside the content is
 * inert, which is what an empty state should be.
 */
export function MenuEmptyNote({
  /** What the menu is missing, in the plural. Shown as "No <what>". */
  what = "menu items",
}: {
  what?: string;
}) {
  return (
    <div
      data-menu-empty=""
      role="presentation"
      className="px-2 py-1.5 text-sm italic text-muted-foreground"
    >
      No {what}
    </div>
  );
}
