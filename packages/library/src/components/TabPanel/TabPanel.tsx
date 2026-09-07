"use client";
import * as React from "react";
import { z } from "zod";

/**
 * Passthrough TabPanel — the v2 schema's TabsNode encodes panels as a
 * tabs[] metadata array + matching children, with no per-panel wrapper.
 * The LLM-generated schemas, however, often emit `<Tabs><TabPanel
 * label="…" value="…">…children…</TabPanel></Tabs>` straight out of v1,
 * and it is also what the editor produces: `Tabs.slots.accepts` is
 * `["TabPanel"]`, so a TabPanel is the only thing a user can drop into a
 * Tabs. We therefore register it as a transparent container.
 *
 * Outside a Tabs it shows its label as a small heading on a card, so a
 * stray panel is not an unlabelled anonymous box. INSIDE a Tabs that chrome
 * is wrong: the tab strip already carries the label (Tabs derives it from
 * this very prop), so drawing a second heading and a second border would
 * put the panel title on screen twice inside a box the tab body already
 * provides. `InsideTabsContext` is how Tabs says which case this is.
 */
export const InsideTabsContext = React.createContext(false);

export const TabPanelProps = z
  .object({
    label: z.string().min(1),
    // Empty is legal: the registry default for TabPanel.value is "" and a
    // dropped panel has no id to offer yet. Requiring min(1) only pushed every
    // freshly dropped panel down validateProps' best-effort coercion path for
    // no gain — Tabs falls back to a positional id when this is blank.
    value: z.string().default(""),
  })
  .strict();

export type TabPanelPropsType = z.infer<typeof TabPanelProps>;

export interface TabPanelProps_ extends TabPanelPropsType {
  children?: React.ReactNode;
}

export function TabPanel({ label, children }: TabPanelProps_) {
  const insideTabs = React.useContext(InsideTabsContext);
  if (insideTabs) {
    return <div data-tab-panel-label={label}>{children}</div>;
  }
  return (
    <section
      data-tab-panel-label={label}
      className="rounded-md border bg-card text-card-foreground p-4 mb-4"
    >
      <h3 className="text-sm font-semibold tracking-tight text-foreground mb-3">{label}</h3>
      <div>{children}</div>
    </section>
  );
}
