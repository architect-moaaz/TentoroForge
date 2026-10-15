"use client";

import { Badge } from "@/components/ui/badge";

type Props =
  | { kind: "org"; status: string }
  | { kind: "person"; disabled_at: string | null; platform_role?: string | null }
  | { kind: "app"; status: string; build_in_flight?: boolean; preview_running?: boolean }
  | { kind: "member"; invite_status: string; role: string };

export function StatusBadge(props: Props) {
  if (props.kind === "org") {
    const v = props.status === "active" ? "secondary" : props.status === "blocked" ? "destructive" : "outline";
    return <Badge variant={v}>{props.status}</Badge>;
  }
  if (props.kind === "person") {
    return (
      <span className="inline-flex gap-1">
        {props.disabled_at ? <Badge variant="destructive">disabled</Badge> : <Badge variant="secondary">active</Badge>}
        {props.platform_role === "super_admin" && <Badge variant="outline">super admin</Badge>}
      </span>
    );
  }
  if (props.kind === "app") {
    return (
      <span className="inline-flex gap-1">
        <Badge variant={props.status === "archived" ? "outline" : "secondary"}>{props.status}</Badge>
        {props.build_in_flight && <Badge variant="default">building</Badge>}
        {props.preview_running && <Badge variant="outline">preview on</Badge>}
      </span>
    );
  }
  return (
    <span className="inline-flex gap-1">
      <Badge variant={props.role === "owner" ? "default" : "secondary"}>{props.role}</Badge>
      {props.invite_status !== "accepted" && <Badge variant="outline">{props.invite_status}</Badge>}
    </span>
  );
}
