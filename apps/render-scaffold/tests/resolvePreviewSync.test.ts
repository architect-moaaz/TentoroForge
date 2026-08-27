import { describe, it } from "node:test";
import assert from "node:assert";
import { resolvePreviewSync } from "../src/lib/resolvePreviewSync";

describe("resolvePreviewSync — op:aggregate / op:stats", () => {
  const previewData = {
    stats: { totalCount: 50, activeCount: 32, pendingCount: 18 },
    teamStats: { totalCount: 25, onlineCount: 10 },
    users: [{ id: "1", name: "Alice" }, { id: "2", name: "Bob" }],
  };

  it("resolves op:aggregate + entity:Unknown to previewData.stats", () => {
    const page = {
      dataSources: [{ name: "stats", entity: "Unknown", op: "aggregate" }],
    };
    const result = resolvePreviewSync(page, previewData);
    assert.deepStrictEqual(result["stats"], previewData.stats);
  });

  it("resolves op:stats + entity:Unknown to previewData.stats", () => {
    const page = {
      dataSources: [{ name: "stats", entity: "Unknown", op: "stats" }],
    };
    const result = resolvePreviewSync(page, previewData);
    assert.deepStrictEqual(result["stats"], previewData.stats);
  });

  it("resolves op:aggregate + known entity to <entity>Stats when present", () => {
    const page = {
      dataSources: [{ name: "stats", entity: "Team", op: "aggregate" }],
    };
    const result = resolvePreviewSync(page, previewData);
    assert.deepStrictEqual(result["stats"], previewData.teamStats);
  });

  it("falls back to previewData.stats when named entity has no <entity>Stats key", () => {
    const page = {
      dataSources: [{ name: "stats", entity: "Task", op: "aggregate" }],
    };
    const result = resolvePreviewSync(page, previewData);
    assert.deepStrictEqual(result["stats"], previewData.stats);
  });

  it("resolves op:summary to previewData.stats", () => {
    const page = {
      dataSources: [{ name: "stats", entity: "Unknown", op: "summary" }],
    };
    const result = resolvePreviewSync(page, previewData);
    assert.deepStrictEqual(result["stats"], previewData.stats);
  });

  it("resolves op:count to previewData.stats", () => {
    const page = {
      dataSources: [{ name: "stats", entity: "Unknown", op: "count" }],
    };
    const result = resolvePreviewSync(page, previewData);
    assert.deepStrictEqual(result["stats"], previewData.stats);
  });

  it("returns {} when previewData has no stats and entity is Unknown", () => {
    const page = {
      dataSources: [{ name: "stats", entity: "Unknown", op: "aggregate" }],
    };
    const result = resolvePreviewSync(page, { users: [] });
    assert.deepStrictEqual(result["stats"], {});
  });

  it("still resolves list dataSources independently alongside a stats source", () => {
    const page = {
      dataSources: [
        { name: "records", entity: "Unknown", op: "list" },
        { name: "stats", entity: "Unknown", op: "aggregate" },
      ],
    };
    const result = resolvePreviewSync(page, previewData);
    // stats resolves correctly
    assert.deepStrictEqual(result["stats"], previewData.stats);
    // records has no entity match → empty array
    assert.deepStrictEqual(result["records"], []);
  });
});

describe("resolvePreviewSync — token smoke-test: loadTokensCustom path", () => {
  // Not a file I/O test — just verifies the function is a clean import
  // and returns an empty object when previewData is absent (no crash).
  it("returns {} when previewData is undefined", () => {
    const page = { dataSources: [{ name: "stats", entity: "Team", op: "aggregate" }] };
    const result = resolvePreviewSync(page, undefined);
    assert.deepStrictEqual(result, {});
  });

  it("returns {} when previewData is empty", () => {
    const page = { dataSources: [{ name: "stats", entity: "Team", op: "aggregate" }] };
    const result = resolvePreviewSync(page, {});
    assert.deepStrictEqual(result, {});
  });
});
