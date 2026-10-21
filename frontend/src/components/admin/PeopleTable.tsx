"use client";

import { MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/admin/StatusBadge";
import type { AdminPerson } from "@/lib/admin-types";

export function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function PeopleTable({
  rows, selfId, onDisable, onEnable, onGrant, onRevoke, onImpersonate, onWatchLive, onRemove,
}: {
  rows: AdminPerson[];
  selfId: string;
  onDisable: (p: AdminPerson) => void;
  onEnable: (p: AdminPerson) => void;
  onGrant: (p: AdminPerson) => void;
  onRevoke: (p: AdminPerson) => void;
  onImpersonate: (p: AdminPerson) => void;
  onWatchLive?: (p: AdminPerson) => void;
  /** Remove the login for good (typed confirmation in the page). */
  onRemove?: (p: AdminPerson) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Person</TableHead>
          <TableHead>Organisations</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Last sign-in</TableHead>
          <TableHead className="w-10" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((p) => {
          const self = p.id === selfId;
          return (
            <TableRow key={p.id} data-testid={`person-${p.email}`}>
              <TableCell>
                <div className="font-medium">{p.name}</div>
                <div className="text-xs text-muted-foreground">{p.email}</div>
              </TableCell>
              <TableCell className="text-xs">
                {p.orgs.length === 0 ? <span className="text-muted-foreground">none</span>
                  : p.orgs.map((o) => <div key={o.org_id}>{o.org_name} <span className="text-muted-foreground">· {o.role}{o.status !== "active" ? ` · ${o.status}` : ""}</span></div>)}
              </TableCell>
              <TableCell>
                <StatusBadge kind="person" disabled_at={p.disabled_at} platform_role={p.platform_role} />
                {p.disabled_reason && <div className="mt-1 text-xs text-muted-foreground">{p.disabled_reason}</div>}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{when(p.last_sign_in_at)}</TableCell>
              <TableCell>
                {!self && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="sm" aria-label={`Actions for ${p.email}`}><MoreHorizontal className="h-4 w-4" /></Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {p.platform_role !== "super_admin" && !p.disabled_at && (
                        <>
                          <DropdownMenuItem onClick={() => onImpersonate(p)}>Impersonate</DropdownMenuItem>
                          {onWatchLive && <DropdownMenuItem onClick={() => onWatchLive(p)}>Watch live</DropdownMenuItem>}
                        </>
                      )}
                      {p.disabled_at
                        ? <DropdownMenuItem onClick={() => onEnable(p)}>Enable login</DropdownMenuItem>
                        : <DropdownMenuItem onClick={() => onDisable(p)}>Disable login…</DropdownMenuItem>}
                      <DropdownMenuSeparator />
                      {p.platform_role === "super_admin"
                        ? <DropdownMenuItem onClick={() => onRevoke(p)}>Revoke super admin</DropdownMenuItem>
                        : <DropdownMenuItem onClick={() => onGrant(p)}>Grant super admin</DropdownMenuItem>}
                      {onRemove && p.platform_role !== "super_admin" && (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => onRemove(p)}>
                            Remove login…
                          </DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </TableCell>
            </TableRow>
          );
        })}
        {rows.length === 0 && (
          <TableRow><TableCell colSpan={5} className="text-center text-sm text-muted-foreground">No one matches.</TableCell></TableRow>
        )}
      </TableBody>
    </Table>
  );
}
