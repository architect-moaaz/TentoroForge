import { describe, it, expect } from "vitest";
import {
  Blueprint,
  blueprintJsonSchema,
  BLUEPRINT_SCHEMA_VERSION,
  BlueprintSchema,
} from "../src/index";
import { Page } from "../src/index";

const minimal = {
  schemaVersion: BLUEPRINT_SCHEMA_VERSION,
  application: { id: "app_1", name: "Recruitment", domain: "ATS" },
};

describe("Living Blueprint (PRD §9-25)", () => {
  it("parses from application identity alone; every other section defaults", () => {
    const bp = Blueprint.parse(minimal);
    expect(Object.keys(bp)).toHaveLength(30);
    expect(bp.state).toBe("DISCOVERY");
    expect(bp.version).toBe(1);
    expect(bp.requirements).toEqual([]);
  });

  it("pins the V1 technology constraints (§104) and deploy target (§86)", () => {
    const bp = Blueprint.parse(minimal);
    expect(bp.runtime.framework).toBe("nextjs");
    expect(bp.runtime.language).toBe("typescript");
    expect(bp.database.engine).toBe("postgres");
    expect(bp.deployment.provider).toBe("vercel");
  });

  it("enforces stable ID format (§12)", () => {
    const ok = Blueprint.safeParse({
      ...minimal,
      requirements: [
        {
          id: "REQ-017",
          description: "Recruiter can schedule interviews.",
          evidence: [{ type: "figma", source: "FIGMA-001", node: "220:144" }],
          status: "APPROVED",
        },
      ],
    });
    expect(ok.success).toBe(true);

    const bad = Blueprint.safeParse({
      ...minimal,
      requirements: [{ id: "REQUIREMENT-17", description: "x" }],
    });
    expect(bad.success).toBe(false);
  });

  it("defaults artifacts to PROPOSED and admits OUT_OF_SYNC (§22, §76)", () => {
    const bp = Blueprint.parse({
      ...minimal,
      data: {
        entities: [{ id: "ENTITY-001", name: "Candidate", table: "candidates" }],
      },
    });
    expect(bp.data.entities[0].status).toBe("PROPOSED");
    expect(BlueprintSchema.ArtifactStatus.options).toContain("OUT_OF_SYNC");
  });

  it("declares page states up front so none are discovered late (§33)", () => {
    const bp = Blueprint.parse({
      ...minimal,
      pages: [
        {
          id: "PAGE-001",
          name: "Candidates",
          route: "/candidates",
          purpose: "Manage candidates progressing through recruitment.",
        },
      ],
    });
    expect(bp.pages[0].states).toEqual(["loading", "empty", "populated", "error"]);
    expect(bp.pages[0].responsive.desktop).toBe("primary");
  });

  it("implements the §17 confidence bands", () => {
    const { autonomyFor } = BlueprintSchema;
    expect(autonomyFor(0.95)).toBe("auto_decide");
    expect(autonomyFor(0.8)).toBe("record_assumption");
    expect(autonomyFor(0.5)).toBe("ask_user");
    expect(autonomyFor(0.2)).toBe("block");
  });

  it("emits a JSON Schema contract for the Python side", () => {
    const js = blueprintJsonSchema() as { properties?: Record<string, unknown> };
    expect(Object.keys(js.properties ?? {})).toHaveLength(30);
  });

  it("makes a data-less widget unrepresentable (§35)", () => {
    // widget_data_source_guard existed to rebind hardcoded stat widgets.
    const hardcoded = Blueprint.safeParse({
      ...minimal,
      widgets: [{ id: "WIDGET-001", page: "PAGE-001", kind: "metric", label: "Open roles" }],
    });
    expect(hardcoded.success).toBe(false);

    const bound = Blueprint.safeParse({
      ...minimal,
      widgets: [{
        id: "WIDGET-001", page: "PAGE-001", kind: "metric", label: "Open roles",
        dataSource: { op: "aggregate", entity: "ENTITY-001", aggregation: "count" },
      }],
    });
    expect(bound.success).toBe(true);
  });

  it("makes an aggregate without an aggregation unrepresentable (§35)", () => {
    // aggregate_metrics_guard existed to fill these in after the fact.
    const bad = Blueprint.safeParse({
      ...minimal,
      widgets: [{
        id: "WIDGET-001", page: "PAGE-001", kind: "metric", label: "x",
        dataSource: { op: "aggregate", entity: "ENTITY-001" },
      }],
    });
    expect(bad.success).toBe(false);
  });

  it("makes a series without a grouping unrepresentable (§35)", () => {
    // chart_data_source_guard existed to convert hardcoded chart arrays.
    const bad = Blueprint.safeParse({
      ...minimal,
      widgets: [{
        id: "WIDGET-001", page: "PAGE-001", kind: "chart", label: "x",
        dataSource: { op: "series", entity: "ENTITY-001", aggregation: "count" },
      }],
    });
    expect(bad.success).toBe(false);
  });

  it("does not disturb existing package exports", () => {
    expect(typeof Page.parse).toBe("function");
  });
});
