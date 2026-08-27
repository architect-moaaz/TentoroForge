"use client";

import { IREditor } from "@/components/ir-editor/IREditor";

/**
 * Standalone IR Editor demo page.
 * Access at: http://localhost:6501/ir-demo
 */
export default function IRDemoPage() {
  return (
    <div className="h-screen w-screen">
      <IREditor projectId="test-ir-demo" />
    </div>
  );
}
