"use client";

import Link from "next/link";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { when } from "@/components/admin/PeopleTable";
import type { AdminOrg } from "@/lib/admin-types";

export function OrgsTable({ rows }: { rows: AdminOrg[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Organisation</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Members</TableHead>
          <TableHead className="text-right">Apps</TableHead>
          <TableHead>Owner</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((o) => (
          <TableRow key={o.id}>
            <TableCell>
              <Link href={`/admin/orgs/${o.id}`} className="font-medium hover:underline">{o.name}</Link>
              <div className="text-xs text-muted-foreground">/{o.slug}</div>
            </TableCell>
            <TableCell>
              <StatusBadge kind="org" status={o.status} />
              {o.status_reason && <div className="mt-1 text-xs text-muted-foreground">{o.status_reason}</div>}
            </TableCell>
            <TableCell className="text-right">{o.members}</TableCell>
            <TableCell className="text-right">{o.apps}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{o.owner_email || "—"}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{when(o.created_at)}</TableCell>
          </TableRow>
        ))}
        {rows.length === 0 && (
          <TableRow><TableCell colSpan={6} className="text-center text-sm text-muted-foreground">No organisation matches.</TableCell></TableRow>
        )}
      </TableBody>
    </Table>
  );
}
