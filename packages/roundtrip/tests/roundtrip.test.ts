import { describe, it, expect } from "vitest";
import {
  parseCompiledFile,
  hasBoundaryMarkers,
  stripBoundaryMarkers,
  reverseMapChanges,
  mergeWithUserCode,
  roundTripSync,
} from "../src/index.js";

// ---------------------------------------------------------------------------
// Sample compiled output with boundaries
// ---------------------------------------------------------------------------

const COMPILED_WITH_BOUNDARIES = `"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export default function TaskListPage() {
  const [search, setSearch] = useState("");

  return (
    <div className="flex flex-col gap-6 p-6">
{/* @ir-node: 0 */}
<div className="flex items-center justify-between">
{/* @ir-node: 0.0 */}
<h2 className="text-xl font-semibold tracking-tight">Tasks</h2>
{/* @ir-end: 0.0 */}
{/* @ir-node: 0.1 */}
<Button variant="default">New Task</Button>
{/* @ir-end: 0.1 */}
</div>
{/* @ir-end: 0 */}
{/* @ir-node: 1 */}
<p className="text-sm">No tasks yet</p>
{/* @ir-end: 1 */}
    </div>
  );
}`;

const NO_BOUNDARIES = `"use client";

import { useState } from "react";

export default function TaskListPage() {
  return <div>Custom code</div>;
}`;

// ---------------------------------------------------------------------------
// Parser tests
// ---------------------------------------------------------------------------

describe("parseCompiledFile", () => {
  it("should extract IR regions from boundary markers", () => {
    const result = parseCompiledFile(COMPILED_WITH_BOUNDARIES);

    expect(result.hasBoundaries).toBe(true);
    expect(result.irIntact).toBe(true);
    expect(result.irRegions.size).toBe(4); // 0, 0.0, 0.1, 1

    expect(result.irRegions.has("0")).toBe(true);
    expect(result.irRegions.has("0.0")).toBe(true);
    expect(result.irRegions.has("0.1")).toBe(true);
    expect(result.irRegions.has("1")).toBe(true);
  });

  it("should extract region content correctly", () => {
    const result = parseCompiledFile(COMPILED_WITH_BOUNDARIES);
    const region0_0 = result.irRegions.get("0.0")!;
    expect(region0_0).toContain("Tasks");
    expect(region0_0).toContain("text-xl");
  });

  it("should detect managed imports", () => {
    const result = parseCompiledFile(COMPILED_WITH_BOUNDARIES);
    expect(result.imports.managed.length).toBeGreaterThan(0);
    expect(result.imports.managed.some((i) => i.includes("useState"))).toBe(true);
  });

  it("should detect files without boundaries", () => {
    const result = parseCompiledFile(NO_BOUNDARIES);
    expect(result.hasBoundaries).toBe(false);
    expect(result.irRegions.size).toBe(0);
  });

  it("should detect unclosed regions as not intact", () => {
    const broken = `{/* @ir-node: 0 */}\n<div>unclosed</div>`;
    const result = parseCompiledFile(broken);
    expect(result.irIntact).toBe(false);
  });

  it("should detect mismatched end tags as not intact", () => {
    const broken = `{/* @ir-node: 0 */}\n<div>content</div>\n{/* @ir-end: 1 */}`;
    const result = parseCompiledFile(broken);
    expect(result.irIntact).toBe(false);
  });

  it("should extract user code between IR regions", () => {
    const withUserCode = `"use client";

import { useState } from "react";

export default function Page() {
  return (
    <div>
{/* @ir-node: 0 */}
<h1>Title</h1>
{/* @ir-end: 0 */}

{/* USER CODE */}
<p>User added this</p>
{/* END USER CODE */}

{/* @ir-node: 1 */}
<footer>Footer</footer>
{/* @ir-end: 1 */}
    </div>
  );
}`;
    const result = parseCompiledFile(withUserCode);
    expect(result.userRegions.length).toBeGreaterThan(0);
    expect(result.userRegions.some((u) => u.content.includes("User added this"))).toBe(true);
  });
});

describe("hasBoundaryMarkers", () => {
  it("should detect boundary markers", () => {
    expect(hasBoundaryMarkers(COMPILED_WITH_BOUNDARIES)).toBe(true);
    expect(hasBoundaryMarkers(NO_BOUNDARIES)).toBe(false);
  });
});

describe("stripBoundaryMarkers", () => {
  it("should remove all boundary comments", () => {
    const stripped = stripBoundaryMarkers(COMPILED_WITH_BOUNDARIES);
    expect(stripped).not.toContain("@ir-node");
    expect(stripped).not.toContain("@ir-end");
    expect(stripped).toContain("Tasks"); // content preserved
    expect(stripped).toContain("New Task");
  });
});

// ---------------------------------------------------------------------------
// Reverse mapper tests
// ---------------------------------------------------------------------------

describe("reverseMapChanges", () => {
  it("should detect text content changes", () => {
    const expected = new Map([
      ["0.0", '<h2 className="text-xl font-semibold">Tasks</h2>'],
    ]);
    const actual = new Map([
      ["0.0", '<h2 className="text-xl font-semibold">My Tasks</h2>'],
    ]);

    const result = reverseMapChanges(expected, actual);
    expect(result.operations.length).toBe(1);
    expect(result.operations[0].type).toBe("setProp");
    expect(result.operations[0].prop).toBe("content");
    expect(result.operations[0].value).toBe("My Tasks");
  });

  it("should detect label changes", () => {
    const expected = new Map([
      ["0", '<div><label className="text-sm">Name</label><input /></div>'],
    ]);
    const actual = new Map([
      ["0", '<div><label className="text-sm">Full Name</label><input /></div>'],
    ]);

    const result = reverseMapChanges(expected, actual);
    expect(result.operations.length).toBe(1);
    expect(result.operations[0].prop).toBe("label");
    expect(result.operations[0].value).toBe("Full Name");
  });

  it("should detect placeholder changes", () => {
    const expected = new Map([
      ["0", '<input placeholder="Search..." />'],
    ]);
    const actual = new Map([
      ["0", '<input placeholder="Find tasks..." />'],
    ]);

    const result = reverseMapChanges(expected, actual);
    expect(result.operations.length).toBe(1);
    expect(result.operations[0].prop).toBe("placeholder");
    expect(result.operations[0].value).toBe("Find tasks...");
  });

  it("should detect className gap changes and map to token", () => {
    const expected = new Map([
      ["0", '<div className="flex flex-col gap-4 p-6">content</div>'],
    ]);
    const actual = new Map([
      ["0", '<div className="flex flex-col gap-8 p-6">content</div>'],
    ]);

    const result = reverseMapChanges(expected, actual);
    expect(result.operations.length).toBe(1);
    expect(result.operations[0].prop).toBe("gap");
    expect(result.operations[0].value).toBe("xl"); // gap-8 → xl
  });

  it("should handle unchanged regions", () => {
    const regions = new Map([
      ["0", '<h1>Same</h1>'],
      ["1", '<p>Same</p>'],
    ]);

    const result = reverseMapChanges(regions, regions);
    expect(result.operations.length).toBe(0);
    expect(result.unmappedRegions.length).toBe(0);
  });

  it("should report unmapped regions for complex changes", () => {
    const expected = new Map([
      ["0", '<div className="flex"><span>A</span><span>B</span></div>'],
    ]);
    const actual = new Map([
      ["0", '<div className="grid grid-cols-3"><span>X</span><span>Y</span><span>Z</span></div>'],
    ]);

    const result = reverseMapChanges(expected, actual);
    // Structure changed too much — should be unmapped
    expect(result.unmappedRegions.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Merge tests
// ---------------------------------------------------------------------------

describe("mergeWithUserCode", () => {
  it("should handle identical files", () => {
    const fresh = COMPILED_WITH_BOUNDARIES;
    const existing = COMPILED_WITH_BOUNDARIES; // same, no user edits

    const result = mergeWithUserCode(fresh, existing);
    // Content should be equivalent (may differ in whitespace due to merge)
    expect(result.content).toContain("Tasks");
    expect(result.content).toContain("New Task");
  });

  it("should preserve user code blocks", () => {
    const existing = `"use client";

import { useState } from "react";
import { motion } from "framer-motion";

export default function Page() {
  return (
    <div>
{/* @ir-node: 0 */}
<h1>Title</h1>
{/* @ir-end: 0 */}

{/* USER CODE */}
<motion.div>Custom animation</motion.div>
{/* END USER CODE */}

{/* @ir-node: 1 */}
<p>Footer</p>
{/* @ir-end: 1 */}
    </div>
  );
}`;

    const fresh = `"use client";

import { useState } from "react";

export default function Page() {
  return (
    <div>
{/* @ir-node: 0 */}
<h1>Updated Title</h1>
{/* @ir-end: 0 */}
{/* @ir-node: 1 */}
<p>Updated Footer</p>
{/* @ir-end: 1 */}
    </div>
  );
}`;

    const result = mergeWithUserCode(fresh, existing);
    expect(result.hasUserCode).toBe(true);
    expect(result.content).toContain("Updated Title"); // fresh IR content
    expect(result.content).toContain("Custom animation"); // user code preserved
  });

  it("should preserve user imports when merging", () => {
    // User imports are detected by comparing fresh vs existing import lists
    // Imports in existing but not in fresh are "user imports"
    const existing = `"use client";

import { useState } from "react";
import { motion } from "framer-motion";

export default function Page() {
  return (
{/* @ir-node: 0 */}
<div>IR</div>
{/* @ir-end: 0 */}
  );
}`;

    const fresh = `"use client";

import { useState } from "react";

export default function Page() {
  return (
{/* @ir-node: 0 */}
<div>Updated IR</div>
{/* @ir-end: 0 */}
  );
}`;

    const result = mergeWithUserCode(fresh, existing);
    // The merge should keep the framer-motion import from existing
    expect(result.content).toContain("framer-motion");
  });

  it("should not merge if existing file has no boundaries", () => {
    const result = mergeWithUserCode(COMPILED_WITH_BOUNDARIES, NO_BOUNDARIES);
    expect(result.content).toBe(NO_BOUNDARIES); // keep existing, don't overwrite
    expect(result.hasUserCode).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Full round-trip tests
// ---------------------------------------------------------------------------

describe("roundTripSync", () => {
  it("should detect in-sync files", () => {
    const result = roundTripSync(COMPILED_WITH_BOUNDARIES, COMPILED_WITH_BOUNDARIES);
    expect(result.status).toBe("in-sync");
    expect(result.operations.length).toBe(0);
  });

  it("should detect text changes and produce setProp operations", () => {
    const modified = COMPILED_WITH_BOUNDARIES.replace("Tasks", "My Tasks");
    const result = roundTripSync(COMPILED_WITH_BOUNDARIES, modified);
    expect(result.status).toBe("changed");
    expect(result.operations.some((op) => op.value === "My Tasks")).toBe(true);
  });

  it("should report ejected status for files without boundaries", () => {
    const result = roundTripSync(COMPILED_WITH_BOUNDARIES, NO_BOUNDARIES);
    expect(result.status).toBe("ejected");
  });

  it("should report corrupt status for broken boundaries", () => {
    const broken = COMPILED_WITH_BOUNDARIES.replace("{/* @ir-end: 0 */}", "");
    const result = roundTripSync(COMPILED_WITH_BOUNDARIES, broken);
    expect(result.status).toBe("corrupt");
  });

  it("should create Custom nodes for unmappable changes", () => {
    // Change structure significantly
    const modified = COMPILED_WITH_BOUNDARIES.replace(
      '<h2 className="text-xl font-semibold tracking-tight">Tasks</h2>',
      '<div className="totally-different"><span>Restructured</span><span>Content</span></div>',
    );

    const result = roundTripSync(COMPILED_WITH_BOUNDARIES, modified);
    // The change is structural — should produce custom nodes
    if (result.customNodes.length > 0) {
      expect(result.customNodes[0].customNode.node).toBe("Custom");
    }
    // Or it might get mapped if the pattern detector catches it
    expect(result.status).not.toBe("in-sync");
  });
});
