"use client";

import { useEffect, useState } from "react";

/**
 * Claude-style "thinking" gerunds. Cycled while the build is running to give
 * the wait a bit of personality (à la Claude's "Ruminating…", "Pondering…").
 */
export const FLAVOR_GERUNDS = [
  "Ruminating",
  "Pondering",
  "Cogitating",
  "Percolating",
  "Musing",
  "Conjuring",
  "Marshalling",
  "Deliberating",
  "Finessing",
  "Noodling",
  "Scheming",
  "Tinkering",
  "Orchestrating",
  "Contemplating",
  "Brewing",
  "Simmering",
  "Distilling",
  "Synthesizing",
  "Composing",
  "Calibrating",
  "Untangling",
  "Wrangling",
  "Sketching",
  "Incubating",
  "Mulling",
  "Concocting",
  "Devising",
  "Envisioning",
  "Crystallizing",
  "Harmonizing",
  "Weaving",
  "Puzzling",
  "Ideating",
  "Formulating",
  "Divining",
  "Channeling",
  "Whittling",
  "Polishing",
  "Refining",
  "Fermenting",
  "Germinating",
  "Percolating",
  "Assembling",
  "Sculpting",
  "Threading",
  "Plotting",
  "Dreaming",
  "Reticulating",
];

/**
 * Returns a gerund that changes every `intervalMs` while `active` is true.
 * Frozen (returns the last value) when inactive, so it settles rather than
 * flickering once generation stops.
 */
export function useFlavorText(active: boolean, intervalMs = 3000): string {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setI((n) => (n + 1) % FLAVOR_GERUNDS.length), intervalMs);
    return () => clearInterval(t);
  }, [active, intervalMs]);
  return FLAVOR_GERUNDS[i];
}
