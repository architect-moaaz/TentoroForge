/** The cockpit's reads and writes, and the query keys the pages share. */
import { api } from "@/lib/api";
import type {
  AdminApp,
  AdminFeature,
  AdminMember,
  AdminOrg,
  AdminOverview,
  AdminPerson,
  AuditRow,
  Balance,
  CreditEntry,
  CreditKind,
  ImpersonationGrant,
  LimitStanding,
  Limits,
  OrgBalanceRow,
  OrgFeatures,
  Paged,
  TeardownReport,
} from "@/lib/admin-types";

function qs(params: Record<string, string | number | undefined | null>): string {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out.set(k, String(v));
  }
  const s = out.toString();
  return s ? `?${s}` : "";
}

export const adminKeys = {
  overview: ["admin", "overview"] as const,
  people: (q: string, page: number) => ["admin", "people", q, page] as const,
  orgs: (q: string, status: string, page: number) => ["admin", "orgs", q, status, page] as const,
  org: (id: string) => ["admin", "org", id] as const,
  members: (id: string) => ["admin", "org", id, "members"] as const,
  apps: (q: string, org: string, page: number) => ["admin", "apps", q, org, page] as const,
  credits: ["admin", "credits"] as const,
  creditEntries: (id: string) => ["admin", "credits", id] as const,
  limits: ["admin", "credits", "limits"] as const,
  features: ["admin", "features"] as const,
  orgFeatures: (id: string) => ["admin", "org", id, "features"] as const,
  audit: (filters: Record<string, string>, page: number) => ["admin", "audit", filters, page] as const,
};

export const adminApi = {
  overview: () => api.get<AdminOverview>("/api/admin/overview"),

  people: (q: string, page = 1) => api.get<Paged<AdminPerson>>(`/api/admin/people${qs({ q, page })}`),
  disable: (id: string, reason: string) => api.post<AdminPerson>(`/api/admin/people/${id}/disable`, { reason }),
  enable: (id: string) => api.post<AdminPerson>(`/api/admin/people/${id}/enable`),
  grant: (id: string) => api.post<AdminPerson>(`/api/admin/people/${id}/super-admin`),
  revoke: (id: string) => api.delete<AdminPerson>(`/api/admin/people/${id}/super-admin`),
  impersonate: (id: string) => api.post<ImpersonationGrant>(`/api/admin/people/${id}/impersonate`),

  orgs: (q: string, status: string, page = 1) =>
    api.get<Paged<AdminOrg>>(`/api/admin/orgs${qs({ q, status, page })}`),
  org: (id: string) => api.get<AdminOrg>(`/api/admin/orgs/${id}`),
  block: (id: string, reason: string) => api.post<AdminOrg>(`/api/admin/orgs/${id}/block`, { reason }),
  remove: (id: string, reason: string) => api.post<AdminOrg>(`/api/admin/orgs/${id}/remove`, { reason }),
  reinstate: (id: string) => api.post<AdminOrg>(`/api/admin/orgs/${id}/reinstate`),
  purge: (id: string, confirm_slug: string) =>
    api.post<TeardownReport & { org_id: string }>(`/api/admin/orgs/${id}/purge`, { confirm_slug }),

  members: (id: string) => api.get<AdminMember[]>(`/api/admin/orgs/${id}/members`),
  addMember: (id: string, email: string, role: string) =>
    api.post<AdminMember>(`/api/admin/orgs/${id}/members`, { email, role }),
  setRole: (id: string, userId: string, role: string) =>
    api.patch<AdminMember>(`/api/admin/orgs/${id}/members/${userId}`, { role }),
  removeMember: (id: string, userId: string) => api.delete<unknown>(`/api/admin/orgs/${id}/members/${userId}`),
  transferOwnership: (id: string, userId: string) =>
    api.post<AdminMember[]>(`/api/admin/orgs/${id}/transfer-ownership`, { user_id: userId }),
  cancelInvite: (id: string, inviteId: string) => api.delete<unknown>(`/api/admin/orgs/${id}/invites/${inviteId}`),
  resendInvite: (id: string, inviteId: string) =>
    api.post<AdminMember & { accept_path: string; emailed: boolean }>(`/api/admin/orgs/${id}/invites/${inviteId}/resend`),

  apps: (q: string, org: string, page = 1) => api.get<Paged<AdminApp>>(`/api/admin/apps${qs({ q, org_id: org, page })}`),
  stopBuild: (id: string) => api.post<AdminApp>(`/api/admin/apps/${id}/stop-build`),
  stopPreview: (id: string) => api.post<AdminApp>(`/api/admin/apps/${id}/stop-preview`),
  archive: (id: string) => api.post<AdminApp>(`/api/admin/apps/${id}/archive`),
  unarchive: (id: string) => api.post<AdminApp>(`/api/admin/apps/${id}/unarchive`),
  deleteApp: (id: string, confirm_short_id: string) =>
    api.post<TeardownReport & { project_id: string }>(`/api/admin/apps/${id}/delete`, { confirm_short_id }),

  credits: () => api.get<{ build_estimate_usd: number; orgs: OrgBalanceRow[] }>("/api/admin/credits/orgs"),
  creditEntries: (id: string) =>
    api.get<{ org_id: string; name: string; slug: string; balance: Balance; limits: LimitStanding[]; entries: CreditEntry[]; build_estimate_usd: number }>(
      `/api/admin/credits/orgs/${id}/entries`),
  addEntry: (id: string, body: { amount_usd: number; kind: CreditKind; note: string }) =>
    api.post<CreditEntry>(`/api/admin/credits/orgs/${id}/entries`, body),
  setLimits: (scope_kind: string, scope_id: string, limits: Limits) =>
    api.put<{ limits: Limits }>("/api/admin/credits/limits", { scope_kind, scope_id, ...limits }),

  features: () => api.get<{ groups: string[]; features: AdminFeature[] }>("/api/admin/features"),
  setPlatformFeature: (key: string, enabled: boolean | null, reason: string) =>
    api.put<{ key: string; enabled_by_default: boolean }>(`/api/admin/features/${key}`, { enabled, reason }),
  orgFeatures: (id: string) => api.get<OrgFeatures>(`/api/admin/orgs/${id}/features`),
  setOrgFeature: (id: string, key: string, enabled: boolean | null, reason: string) =>
    api.put<OrgFeatures>(`/api/admin/orgs/${id}/features/${key}`, { enabled, reason }),

  audit: (filters: Record<string, string>, page = 1, limit = 50) =>
    api.get<AuditRow[]>(`/api/admin/audit${qs({ ...filters, limit, offset: (page - 1) * limit })}`),
};
