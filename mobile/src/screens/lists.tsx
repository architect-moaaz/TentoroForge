import { ListScreen } from '@/components/list-screen';

const fullName = (p: { first_name?: string | null; last_name?: string | null; email?: string }) =>
  [p.first_name, p.last_name].filter(Boolean).join(' ') || p.email || 'Unnamed';

/** The drafts room stores times as epoch numbers; accept seconds or milliseconds. */
const dateOf = (value: number | string) => {
  const n = typeof value === 'number' ? (value < 1e12 ? value * 1000 : value) : value;
  return new Date(n).toLocaleDateString();
};

export function PeopleScreen() {
  return (
    <ListScreen<{
      id: string;
      email: string;
      first_name: string | null;
      last_name: string | null;
      title: string | null;
      is_active: boolean;
    }>
      path={(orgId) => `/api/orgs/${orgId}/people?limit=200`}
      icon="users"
      searchPlaceholder="Search people"
      emptyTitle="No people yet"
      emptyText="Add people on the web app."
      toRow={(p) => ({
        id: p.id,
        title: fullName(p),
        subtitle: p.title,
        meta: p.email,
        badge: p.is_active ? null : 'inactive',
      })}
    />
  );
}

export function DepartmentsScreen() {
  return (
    <ListScreen<{ id: string; name: string; description: string | null }>
      path={(orgId) => `/api/orgs/${orgId}/departments`}
      icon="briefcase"
      searchPlaceholder="Search departments"
      emptyTitle="No departments yet"
      emptyText="Add departments on the web app."
      toRow={(d) => ({ id: d.id, title: d.name, subtitle: d.description })}
    />
  );
}

export function TeamsScreen() {
  return (
    <ListScreen<{ id: string; name: string; description: string | null }>
      path={(orgId) => `/api/orgs/${orgId}/teams`}
      icon="user-check"
      searchPlaceholder="Search teams"
      emptyTitle="No teams yet"
      emptyText="Add teams on the web app."
      toRow={(t) => ({ id: t.id, title: t.name, subtitle: t.description })}
    />
  );
}

export function RolesScreen() {
  return (
    <ListScreen<{ id: string; name: string; description: string | null; is_default: boolean }>
      path={(orgId) => `/api/orgs/${orgId}/roles`}
      icon="shield"
      emptyTitle="No roles yet"
      emptyText="Add roles on the web app."
      toRow={(r) => ({
        id: r.id,
        title: r.name,
        subtitle: r.description,
        meta: r.is_default ? 'Default role' : null,
      })}
    />
  );
}

export function GroupsScreen() {
  return (
    <ListScreen<{ id: string; name: string; description: string | null; member_count: number }>
      path={(orgId) => `/api/orgs/${orgId}/groups`}
      icon="users"
      searchPlaceholder="Search groups"
      emptyTitle="No groups yet"
      emptyText="Add groups on the web app."
      toRow={(g) => ({
        id: g.id,
        title: g.name,
        subtitle: g.description,
        meta: `${g.member_count} ${g.member_count === 1 ? 'member' : 'members'}`,
      })}
    />
  );
}

export function TemplatesScreen() {
  return (
    <ListScreen<{ slug: string; name: string; description: string; category: string; complexity: string }>
      path={() => '/api/templates'}
      select={(body) => body.templates ?? []}
      icon="layout"
      searchPlaceholder="Search templates"
      emptyTitle="No templates"
      emptyText="No templates are published yet."
      toRow={(t) => ({
        id: t.slug,
        title: t.name,
        subtitle: t.description,
        meta: `${t.category} · ${t.complexity}`,
      })}
    />
  );
}

export function DraftsRoomScreen() {
  return (
    <ListScreen<{ id: string; title: string; updated_at: number; agreed: boolean; messages: number }>
      path={(orgId) => `/api/orgs/${orgId}/drafts-room`}
      icon="edit-3"
      emptyTitle="No drafts yet"
      emptyText="Start a draft on the web app to shape an idea before it becomes a project."
      toRow={(s) => ({
        id: s.id,
        title: s.title || 'Untitled draft',
        meta: `${s.messages} messages · ${dateOf(s.updated_at)}`,
        badge: s.agreed ? 'agreed' : null,
      })}
    />
  );
}

export function DiscoverScreen() {
  return (
    <ListScreen<{
      id: string;
      title: string | null;
      discovery_type: string;
      status: string;
      messages: unknown[];
      updated_at: string;
    }>
      path={(orgId) => `/api/orgs/${orgId}/discovery`}
      icon="star"
      emptyTitle="No discovery sessions"
      emptyText="Start a discovery session on the web app to find what to build."
      toRow={(s) => ({
        id: s.id,
        title: s.title || s.discovery_type,
        meta: `${s.messages?.length ?? 0} messages · ${new Date(s.updated_at).toLocaleDateString()}`,
        badge: s.status,
      })}
    />
  );
}
