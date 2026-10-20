"use client";

import Link from "next/link";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Incident } from "@/lib/admin-types";
import { when } from "@/components/admin/PeopleTable";

const KIND: Record<string, string> = {
  turn_lost: "turn lost", build_lost: "build lost", check_lost: "check lost", platform_fault: "platform fault",
  build_stuck: "build stuck",
};

/** Faults that are Forge's own, shown in red; a process that went away is amber. */
const PLATFORM = new Set(["platform_fault", "build_stuck"]);

/** The recurring faults among `rows`, one per signature, newest first. */
export function recurringFaults(rows: Incident[]): Incident[] {
  const seen = new Set<string>();
  return rows.filter((r) => {
    if (!r.recurring || !r.signature || seen.has(r.signature)) return false;
    seen.add(r.signature);
    return true;
  });
}

export function IncidentsTable({ rows }: { rows: Incident[] }) {
  if (rows.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">Nothing has gone wrong on the record.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow><TableHead>When</TableHead><TableHead>What</TableHead><TableHead>App</TableHead><TableHead>Detail</TableHead></TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={`${r.at}-${i}`} data-testid={`incident-${r.kind}`}>
            <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{when(r.at)}</TableCell>
            <TableCell>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PLATFORM.has(r.kind) ? "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300" : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"}`}>
                {KIND[r.kind] ?? r.kind}
              </span>
              {r.recurring && (
                <span className="ml-1 rounded-full bg-rose-600 px-2 py-0.5 text-xs font-medium text-white"
                      title={(r.apps ?? []).join(", ")} data-testid="incident-recurring">
                  in {(r.apps ?? []).length} apps
                </span>
              )}
              {r.why && <div className="mt-0.5 text-[11px] text-muted-foreground">{r.why}</div>}
            </TableCell>
            <TableCell><Link href={`/admin/apps?q=${encodeURIComponent(r.app)}`} className="font-mono text-xs hover:underline">{r.app}</Link></TableCell>
            <TableCell className="max-w-xl text-sm">{r.detail}{r.path && <code className="ml-1 text-xs text-muted-foreground">{r.path}</code>}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
