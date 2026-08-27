"use client";

/**
 * Dev-only preview for VerifyProgressCard.
 * Shows the four states side by side so a designer can eyeball the chip
 * without triggering a real verify run.
 */
import { VerifyProgressCard } from "@/components/verify/VerifyProgressCard";

const EMPTY = { results: [], summary: null, hints: [] };

export default function VerifyProgressPreview() {
  return (
    <div className="p-8 max-w-3xl mx-auto space-y-8 text-sm">
      <h1 className="text-lg font-semibold">VerifyProgressCard preview</h1>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          1. Just kicked off (verifyActive, no events yet)
        </h2>
        <VerifyProgressCard
          verifyActive
          streaming={{
            status: "Building container image…",
            logs: ["[Journey] Running journey verification..."],
            journey: EMPTY,
          }}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          2. Container booted, walking journeys (mid-run)
        </h2>
        <VerifyProgressCard
          verifyActive
          streaming={{
            status: "Walking journey primary-scan…",
            logs: [
              "[Journey] booted containerized app at http://localhost:56789 (project=verify-9d3f, 47s)",
              "[Journey] Running journey verification...",
            ],
            journey: {
              results: [
                { slug: "primary-scan", status: "passed", duration_ms: 38107 },
              ],
              summary: null,
              hints: [],
            },
          }}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          3. All green (final)
        </h2>
        <VerifyProgressCard
          verifyActive={false}
          streaming={{
            status: null,
            logs: [
              "[Journey] booted containerized app at http://localhost:56790 (project=verify-2b7e, 52s)",
              "[Journey] Journey gate: 2/2 passed in 46s",
            ],
            journey: {
              results: [
                { slug: "primary-scan", status: "passed", duration_ms: 38107 },
                { slug: "admin-approve", status: "passed", duration_ms: 8302 },
              ],
              summary: { mode: "warn", ok: true, total: 2, passed: 2, failed: 0,
                         duration_ms: 46000 },
              hints: [],
            },
          }}
        />
      </section>

      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          4. Partial fail — autofix dispatched
        </h2>
        <VerifyProgressCard
          verifyActive={false}
          streaming={{
            status: null,
            logs: [
              "[Journey] booted containerized app at http://localhost:56791",
              "[Journey] autofix dispatched to workflow-definition",
              "[Journey] second run: 1/2 passed",
            ],
            journey: {
              results: [
                { slug: "primary-scan", status: "failed", duration_ms: 100719 },
                { slug: "admin-approve", status: "passed", duration_ms: 8302 },
              ],
              summary: { mode: "strict", ok: false, total: 2, passed: 1,
                         failed: 1, duration_ms: 113019 },
              hints: [{ target_seam: "workflow-definition" }],
            },
          }}
        />
      </section>

      {/* SV-STRICT-3b — narrated-faults preview */}
      <section className="space-y-2">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground">
          5. SV-STRICT — narrated faults grouped by W-slot
        </h2>
        <VerifyProgressCard
          verifyActive={false}
          streaming={{
            status: null,
            logs: [
              "[Journey] booted containerized app at http://localhost:56792",
              "[Journey] verify pass complete",
            ],
            journey: {
              results: [
                { slug: "member-book-class", status: "failed", duration_ms: 12000 },
              ],
              summary: { mode: "strict", ok: false, total: 1, passed: 0,
                         failed: 1, duration_ms: 12000 },
              hints: [],
            },
            verify: {
              runId: "demo-run",
              startedAt: Date.now() - 60000,
              progress: { done: 1, total: 1, currentUrl: null },
              recentFaults: [],
              status: "done",
              narrated: {
                narratives: [],
                by_w_slot: {
                  when: [
                    { text: "The 'Book Class' button on /schedule doesn't do "
                          + "anything when clicked — no action is declared for it.",
                      priority: "BROKEN", signature: "BUTTON_NO_ACTION_DECLARED",
                      w_slot: "when",
                      component_id: "button:/schedule:book-class",
                      route: "/schedule" },
                  ],
                  how: [
                    { text: "The 'Create Booking' form on /schedule/new "
                          + "crashed on submit — the server returned a 5xx "
                          + "error (BookClass).",
                      priority: "BLOCKER", signature: "FORM_SUBMIT_500_GENERIC",
                      w_slot: "how",
                      component_id: "form:/schedule/new:create",
                      route: "/schedule/new" },
                  ],
                  why: [
                    { text: "The app promised 'Cancel a booking' but no page "
                          + "or workflow fulfills it. A persona said they "
                          + "wanted to do this and nothing in the generated "
                          + "app supports it.",
                      priority: "BROKEN", signature: "PROMISE_NOT_DELIVERED",
                      w_slot: "why",
                      component_id: "promise:member:cancel-booking",
                      route: "promise://member/cancel-booking" },
                  ],
                },
              },
            },
          }}
        />
      </section>
    </div>
  );
}
