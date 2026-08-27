import * as React from "react";
import { z } from "zod";

/**
 * Passthrough TabPanel — the v2 schema's TabsNode encodes panels as a
 * tabs[] metadata array + matching children, with no per-panel wrapper.
 * The LLM-generated schemas, however, often emit `<Tabs><TabPanel
 * label="…" value="…">…children…</TabPanel></Tabs>` straight out of v1.
 * To make those schemas render in the editor canvas (and the generated
 * app), we register TabPanel as a transparent container that shows its
 * label as a small heading and renders its children. It's not a real
 * tabs UI, but it stops the canvas from collapsing to placeholder
 * markers and it preserves the structural intent for editing.
 */
export const TabPanelProps = z
  .object({
    label: z.string().min(1),
    value: z.string().min(1),
  })
  .strict();

export type TabPanelPropsType = z.infer<typeof TabPanelProps>;

export interface TabPanelProps_ extends TabPanelPropsType {
  children?: React.ReactNode;
}

export function TabPanel({ label, children }: TabPanelProps_) {
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
