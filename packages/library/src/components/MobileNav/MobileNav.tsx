"use client";
import * as React from "react";
import Link from "next/link";
import * as RDropdown from "@radix-ui/react-dropdown-menu";
import type { MobileNavPropsType } from "./MobileNav.schema";
import { resolveIcon } from "../../icons";

export interface MobileNavProps extends MobileNavPropsType {}

/**
 * Hamburger nav for mobile viewports. Renders nothing on `md` and above —
 * the desktop nav row in the shell is expected to be wrapped in
 * `hidden md:flex`, so the two swap cleanly at the breakpoint. On mobile
 * a hamburger button opens a dropdown of navigation entries authored as
 * plain link items (label + href); selecting one navigates via next/link.
 */
export function MobileNav({
  items = [],
  triggerIcon = "menu",
  ariaLabel = "Open navigation menu",
  align = "end",
  className,
}: MobileNavProps) {
  const TriggerIcon = resolveIcon(triggerIcon);
  const wrapperClass = ["md:hidden", className].filter(Boolean).join(" ");

  if (!items.length) return null;

  return (
    <div className={wrapperClass} data-mobile-nav="">
      <RDropdown.Root>
        <RDropdown.Trigger asChild>
          <button
            type="button"
            aria-label={ariaLabel}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-input bg-transparent text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {TriggerIcon ? <TriggerIcon size={20} aria-hidden="true" /> : "≡"}
          </button>
        </RDropdown.Trigger>
        <RDropdown.Portal>
          <RDropdown.Content
            align={align}
            sideOffset={6}
            className="z-50 min-w-[12rem] rounded-md border border-input bg-white p-1 shadow-md"
          >
            {items.map((it) => {
              const ItemIcon = it.icon ? resolveIcon(it.icon) : null;
              return (
                <RDropdown.Item
                  key={it.href + it.label}
                  asChild
                  className="flex cursor-pointer items-center gap-2 rounded px-3 py-2 text-sm text-foreground outline-none hover:bg-muted focus:bg-muted"
                >
                  <Link href={it.href}>
                    {ItemIcon && <ItemIcon size={16} aria-hidden="true" />}
                    <span>{it.label}</span>
                  </Link>
                </RDropdown.Item>
              );
            })}
          </RDropdown.Content>
        </RDropdown.Portal>
      </RDropdown.Root>
    </div>
  );
}
