import { describe, it, expect } from "vitest";
import { nextSortState, dbRowsUrl } from "./db-rows";

describe("nextSortState", () => {
  it("sorts a new column ascending", () => {
    expect(nextSortState({ sort: null, dir: "asc" }, "name")).toEqual({ sort: "name", dir: "asc" });
  });
  it("toggles asc -> desc on the same column", () => {
    expect(nextSortState({ sort: "name", dir: "asc" }, "name")).toEqual({ sort: "name", dir: "desc" });
  });
  it("clears sort on the third click of the same column", () => {
    expect(nextSortState({ sort: "name", dir: "desc" }, "name")).toEqual({ sort: null, dir: "asc" });
  });
  it("switching columns restarts at ascending", () => {
    expect(nextSortState({ sort: "name", dir: "desc" }, "age")).toEqual({ sort: "age", dir: "asc" });
  });
});

describe("dbRowsUrl", () => {
  it("builds a url without sort", () => {
    expect(dbRowsUrl("p1", "users", 0, 50, null, "asc")).toBe(
      "/api/projects/p1/db/rows?table=users&limit=50&offset=0",
    );
  });
  it("includes offset for later pages and the sort params", () => {
    expect(dbRowsUrl("p1", "users", 2, 50, "name", "desc")).toBe(
      "/api/projects/p1/db/rows?table=users&limit=50&offset=100&sort=name&dir=desc",
    );
  });
  it("url-encodes the table and sort", () => {
    expect(dbRowsUrl("p1", "a b", 0, 50, "c d", "asc")).toBe(
      "/api/projects/p1/db/rows?table=a%20b&limit=50&offset=0&sort=c%20d&dir=asc",
    );
  });
});
