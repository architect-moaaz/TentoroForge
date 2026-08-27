import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { buildDefaultRegistry } from "../src/buildDefaultRegistry";

/**
 * Drift guard: composition-anchor definitions (backend/services/composition/
 * anchors.json) name a component in the `component` field for each anchor.
 * For the v1 anchors we've actually implemented in packages/library/src/anchors,
 * that component name MUST exist in the runtime registry — otherwise the
 * deterministic page builder resolves an anchor to a missing component and
 * the renderer falls back to a "⚠ <Type>" placeholder.
 *
 * If this test starts failing on a NEW anchor name, either:
 *   (a) build the component in packages/library/src/anchors/{Name}/ + register
 *       it in buildDefaultRegistry, or
 *   (b) add it to V1_IMPLEMENTED_ANCHORS below only after (a) is done.
 */

// The anchors we've promised to ship (Slice 2, member_home).
// Extend this set as more recipes get their anchors built.
const V1_IMPLEMENTED_ANCHORS = new Set<string>([
  // member_home
  "pinned_moment_hero",
  "vitals_in_context",
  "scan_strip",
  "recs_rail_reasoned",
  "community_pulse",
  "sticky_primary_cta",
  // shopper_home
  "featured_moment_hero",
  "reasons_to_return_row",
  "trending_rail",
  "taste_recs_rail",
  "brand_story_pulse",
  "cart_cta",
  // operator_console
  "attention_queue_hero",
  "sla_vitals_strip",
  "live_event_log",
  "team_status_board",
  "shift_metrics_rail",
  "emergency_action_rail",
  // manager_overview
  "team_glance_hero",
  "priorities_strip",
  "calendar_week",
  "escalations_queue",
  "recognition_feed",
  // learner_home
  "resume_hero",
  "progress_vitals",
  "up_next_rail",
  "peer_wins_feed",
  "discovery_rail",
  // patron_events
  "next_event_hero",
  "calendar_strip",
  "following_rail",
  "venue_pulse",
  // creator_workspace
  "draft_focus_hero",
  "inventory_rail",
  "ambient_metric_row",
  "next_actions_list",
  "recent_activity_feed",
  "publish_cta",
  // field_worker_today
  "next_job_hero",
  "route_strip",
  "job_checklist",
  "team_comms_thread",
  "completion_capture",
  "emergency_call_button",
  // analyst_workspace
  "narrative_headline",
  "trend_chart_annotated",
  "segment_breakdown",
  "saved_views_strip",
  "anomaly_feed",
  "share_export_cta",
]);

type AnchorMeta = {
  component?: string;
  impl_status?: string;
};

function loadAnchors(): Record<string, AnchorMeta> {
  const p = resolve(__dirname, "../../../backend/services/composition/anchors.json");
  const raw = readFileSync(p, "utf-8");
  const doc = JSON.parse(raw) as { anchors?: Record<string, AnchorMeta> };
  return doc.anchors ?? {};
}

describe("composition anchors ↔ library registry drift-guard", () => {
  const anchors = loadAnchors();
  const registry = buildDefaultRegistry();
  const registeredNames = new Set(registry.list().map((e) => e.name));

  it("v1-implemented anchors are all present in anchors.json", () => {
    for (const name of V1_IMPLEMENTED_ANCHORS) {
      expect(anchors[name], `anchors.json missing v1 anchor "${name}"`).toBeDefined();
    }
  });

  it("v1-implemented anchors resolve to a registered component", () => {
    for (const anchorName of V1_IMPLEMENTED_ANCHORS) {
      const meta = anchors[anchorName];
      expect(meta.component, `anchor "${anchorName}" has no component name`).toBeTruthy();
      expect(
        registeredNames.has(meta.component!),
        `anchor "${anchorName}" → component "${meta.component}" not registered in buildDefaultRegistry`,
      ).toBe(true);
    }
  });
});
