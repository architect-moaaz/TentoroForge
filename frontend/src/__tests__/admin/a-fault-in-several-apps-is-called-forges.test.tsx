/**
 * The same fault in a second app is almost certainly Forge's: the cockpit says
 * so at the top, once per fault, and marks each row it appears in.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { IncidentsTable, recurringFaults } from "@/components/admin/IncidentsTable";
import type { Incident } from "@/lib/admin-types";

const row = (over: Partial<Incident>): Incident => ({ at: "2026-10-20T14:33:10Z", kind: "build_stuck", app: "0qtb9jiy",
  detail: "page_contracts: InconsistentPageAccess: /cases names no role", ...over });

describe("a fault seen in several apps", () => {
  it("is listed once, newest first, only when it recurs", () => {
    const rows = [
      row({ signature: "s1", recurring: true, apps: ["0qtb9jiy", "fnocleub"] }),
      row({ app: "fnocleub", signature: "s1", recurring: true, apps: ["fnocleub", "qpqhdugb"] }),
      row({ app: "aaaa1111", signature: "s2" }),
    ];
    const shown = recurringFaults(rows);
    expect(shown).toHaveLength(1);
    expect(shown[0].apps).toEqual(["0qtb9jiy", "fnocleub"]);
  });

  it("marks the row with how many apps it hit, and a stuck build as Forge's", () => {
    const html = renderToStaticMarkup(
      <IncidentsTable rows={[row({ signature: "s1", recurring: true, apps: ["0qtb9jiy", "fnocleub", "qpqhdugb"] })]} />,
    );
    expect(html).toContain("build stuck");
    expect(html).toContain("in 3 apps");
    expect(html).toContain("bg-rose-100");
  });
});
