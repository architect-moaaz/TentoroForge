/** What the cockpit reads and writes (`/api/admin/*`). */

export interface AdminOrgMembership {
  org_id: string;
  org_name: string;
  slug: string;
  role: string;
  status: string;
}

export interface AdminPerson {
  id: string;
  email: string;
  name: string;
  auth_provider: string | null;
  platform_role: "super_admin" | null;
  disabled_at: string | null;
  disabled_reason: string | null;
  last_sign_in_at: string | null;
  created_at: string;
  orgs: AdminOrgMembership[];
  spend_30d: number | null;
}

export type OrgStatus = "active" | "blocked" | "removed";

export interface AdminOrg {
  id: string;
  name: string;
  slug: string;
  status: OrgStatus;
  status_reason: string | null;
  status_changed_at: string | null;
  members: number;
  apps: number;
  owner_email: string | null;
  created_at: string;
}

export interface AdminMember {
  id: string;
  user_id: string | null;
  email: string | null;
  name: string | null;
  role: "owner" | "admin" | "member";
  invite_status: "pending" | "accepted" | "declined" | "expired";
  joined_at: string | null;
  created_at: string;
  disabled: boolean;
}

export interface AdminApp {
  id: string;
  short_id: string;
  name: string;
  status: string;
  org: { id: string; name: string; slug: string; status: string } | null;
  owner_email: string | null;
  deployed_url: string | null;
  build_in_flight: boolean;
  preview_running: boolean;
  created_at: string;
  updated_at: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminOverview {
  people: number;
  super_admins: number;
  disabled_logins: number;
  orgs: Record<OrgStatus, number>;
  apps: number;
  deployments: number;
}

export interface AuditRow {
  id: string;
  user_id: string | null;
  actor_user_id: string | null;
  org_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  changes: Record<string, unknown> | null;
  ip_address: string | null;
  request_id: string | null;
  timestamp: string;
}

export interface TeardownReport {
  removed: { step: string; target: string }[];
  failed: { step: string; target: string; error: string }[];
}

export interface Balance {
  known: boolean;
  credit_usd: number;
  spent_usd: number;
  balance_usd: number | null;
  since: string | null;
}

export type Period = "day" | "week" | "month" | "year";
export type Limits = Partial<Record<Period, number>>;

export interface OrgBalanceRow extends Balance {
  org_id: string;
  name: string;
  slug: string;
  status: OrgStatus;
  spent_all_time_usd: number;
  entries: number;
  last_entry: CreditEntry | null;
  limits: Limits;
}

export type CreditKind = "opening" | "top_up" | "adjustment" | "refund";

export interface CreditEntry {
  id: string;
  org_id: string;
  at: number;
  at_iso: string | null;
  amount: number;
  kind: CreditKind;
  note: string;
  by: string;
  by_email: string;
}

export interface LimitStanding {
  scope: string;
  period: Period;
  spent_usd: number;
  limit_usd: number | null;
  left_usd: number | null;
}

export interface OrgSpend {
  org_id: string;
  balance: Balance;
  limits: LimitStanding[];
  limits_set: Limits;
  platform_limits: Limits;
  build_estimate_usd: number;
  report: { total: { cost_usd: number; calls: number } };
}

export interface ImpersonationGrant {
  access_token: string;
  expires_at: string;
  user: AdminPerson;
  default_org_id: string | null;
}

/** A feature as the cockpit sees it: the catalogue, the platform's setting, how many organisations override it. */
export interface FeatureSettingRow {
  enabled: boolean;
  reason: string;
  at: string | null;
  by_email: string | null;
}

export interface AdminFeature {
  key: string;
  name: string;
  description: string;
  group: "build" | "workspace" | "ship" | "integrations";
  default_on: boolean;
  source_out: boolean;
  enforced: "api" | "ui";
  platform: FeatureSettingRow | null;
  enabled_by_default: boolean;
  org_overrides: number;
}

export interface OrgFeatureRow {
  key: string;
  name: string;
  description: string;
  group: "build" | "workspace" | "ship" | "integrations";
  default_on: boolean;
  source_out: boolean;
  enforced: "api" | "ui";
  platform: FeatureSettingRow | null;
  override: FeatureSettingRow | null;
  enabled: boolean;
  source: "default" | "platform" | "org";
}

export interface OrgFeatures {
  org_id: string;
  name: string;
  slug: string;
  status: string;
  features: OrgFeatureRow[];
}

export const FEATURE_GROUP_NAMES: Record<AdminFeature["group"], string> = {
  build: "Build", workspace: "Workspace", ship: "Ship", integrations: "Integrations",
};

/** Something that went wrong on the platform, as the backend recorded it (services/incidents.py). */
export interface Incident {
  at: string;
  kind: "turn_lost" | "build_lost" | "check_lost" | "platform_fault" | "build_stuck" | string;
  app: string;
  detail: string;
  /** The same fault, matched across applications. */
  signature?: string;
  /** Seen in another application too — almost certainly the platform's. */
  recurring?: boolean;
  apps?: string[];
  node?: string;
  why?: string;
  ledger?: string;
  path?: string;
  cause?: string;
}

/** One agent's month (or day, week, year) — `GET /api/admin/agents`. */
export interface AgentStat {
  agent: string;
  name: string;
  title: string;
  room: string;
  calls: number;
  repair_calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  busy_hours: number;
  utilization: number;
  apps: number;
  steps: number;
  done: number;
  failed: number;
  retries: number;
  repairs: number;
  unrepaired: number;
  runs_lost: number;
  reviews: number;
  found: number;
  success_rate: number | null;
  median_s: number | null;
  p90_s: number | null;
  cost_per_step_usd: number | null;
  top_failures: { reason: string; count: number }[];
}

export interface AgentReport {
  period: string;
  from: number;
  to: number;
  agents: AgentStat[];
  totals: {
    calls: number; steps: number; done: number; failed: number; retries: number; repairs: number;
    unrepaired: number; runs_lost: number; reviews: number; found: number; cost_usd: number;
    busy_hours: number; success_rate: number | null; active_agents: number;
  };
  daily: { day: string; calls: number; cost_usd: number; failures: number }[];
}
