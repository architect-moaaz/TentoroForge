"use client";

import Link from "next/link";
import { ExternalLink, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/admin/StatusBadge";
import { when } from "@/components/admin/PeopleTable";
import type { AdminApp } from "@/lib/admin-types";

export function AppsTable({
  rows, onStopBuild, onStopPreview, onArchive, onUnarchive, onDelete, onOpenAsOwner,
}: {
  rows: AdminApp[];
  onStopBuild: (a: AdminApp) => void;
  onStopPreview: (a: AdminApp) => void;
  onArchive: (a: AdminApp) => void;
  onUnarchive: (a: AdminApp) => void;
  onDelete: (a: AdminApp) => void;
  onOpenAsOwner?: (a: AdminApp) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>App</TableHead>
          <TableHead>Organisation</TableHead>
          <TableHead>Owner</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Deployed</TableHead>
          <TableHead>Updated</TableHead>
          <TableHead className="w-10" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((a) => (
          <TableRow key={a.id} data-testid={`app-${a.short_id}`}>
            <TableCell>
              <div className="font-medium">{a.name}</div>
              <div className="text-xs text-muted-foreground">{a.short_id}</div>
            </TableCell>
            <TableCell className="text-xs">
              {a.org ? <Link href={`/admin/orgs/${a.org.id}`} className="hover:underline">{a.org.name}</Link> : "—"}
            </TableCell>
            <TableCell className="text-xs text-muted-foreground">{a.owner_email || "—"}</TableCell>
            <TableCell><StatusBadge kind="app" status={a.status} build_in_flight={a.build_in_flight} preview_running={a.preview_running} /></TableCell>
            <TableCell className="text-xs">
              {a.deployed_url
                ? <a href={a.deployed_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline">live <ExternalLink className="h-3 w-3" /></a>
                : <span className="text-muted-foreground">not published</span>}
            </TableCell>
            <TableCell className="text-xs text-muted-foreground">{when(a.updated_at)}</TableCell>
            <TableCell>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" aria-label={`Actions for ${a.name}`}><MoreHorizontal className="h-4 w-4" /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {onOpenAsOwner && a.owner_email && <DropdownMenuItem onClick={() => onOpenAsOwner(a)}>Open as owner</DropdownMenuItem>}
                  <DropdownMenuItem onClick={() => onStopBuild(a)} disabled={!a.build_in_flight}>Stop build</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onStopPreview(a)} disabled={!a.preview_running}>Stop preview</DropdownMenuItem>
                  <DropdownMenuSeparator />
                  {a.status === "archived"
                    ? <DropdownMenuItem onClick={() => onUnarchive(a)}>Unarchive</DropdownMenuItem>
                    : <DropdownMenuItem onClick={() => onArchive(a)}>Archive</DropdownMenuItem>}
                  <DropdownMenuItem className="text-destructive" onClick={() => onDelete(a)}>Delete…</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </TableCell>
          </TableRow>
        ))}
        {rows.length === 0 && (
          <TableRow><TableCell colSpan={7} className="text-center text-sm text-muted-foreground">No app matches.</TableCell></TableRow>
        )}
      </TableBody>
    </Table>
  );
}
