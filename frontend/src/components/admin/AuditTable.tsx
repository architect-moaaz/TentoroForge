"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { when } from "@/components/admin/PeopleTable";
import type { AuditRow } from "@/lib/admin-types";

export function AuditTable({ rows, names }: { rows: AuditRow[]; names?: Record<string, string> }) {
  const who = (id: string | null) => (id ? names?.[id] || id.slice(0, 8) : "—");
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>When</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>By</TableHead>
          <TableHead>As</TableHead>
          <TableHead>Resource</TableHead>
          <TableHead>Details</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => {
          const impersonated = !!r.actor_user_id && !!r.user_id && r.actor_user_id !== r.user_id;
          return (
            <TableRow key={r.id}>
              <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{when(r.timestamp)}</TableCell>
              <TableCell><code className="text-xs">{r.action}</code></TableCell>
              <TableCell className="text-xs">{who(r.actor_user_id)}</TableCell>
              <TableCell className="text-xs">{impersonated ? <Badge variant="outline">{who(r.user_id)}</Badge> : "—"}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{r.resource_type}{r.resource_id ? ` · ${r.resource_id}` : ""}</TableCell>
              <TableCell>
                {r.changes && (
                  <Popover>
                    <PopoverTrigger asChild>
                      <button className="text-xs text-primary hover:underline">view</button>
                    </PopoverTrigger>
                    <PopoverContent className="w-96">
                      <pre className="max-h-64 overflow-auto text-[11px]">{JSON.stringify(r.changes, null, 2)}</pre>
                    </PopoverContent>
                  </Popover>
                )}
              </TableCell>
            </TableRow>
          );
        })}
        {rows.length === 0 && (
          <TableRow><TableCell colSpan={6} className="text-center text-sm text-muted-foreground">Nothing on the record for this filter.</TableCell></TableRow>
        )}
      </TableBody>
    </Table>
  );
}
