import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AssignType } from "@/types/workflow";

interface OrgEntity {
  id: string;
  label: string;
}

const ENTITY_TYPE_MAP: Partial<Record<AssignType, string>> = {
  role: "roles",
  group: "groups",
  department: "departments",
  person: "people",
  team: "teams",
};

interface OrgEntityRaw {
  id: string;
  name?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
}

function formatLabel(item: OrgEntityRaw, entityKey: string): string {
  if (entityKey === "people") {
    const first = item.first_name || "";
    const last = item.last_name || "";
    const email = item.email ? ` (${item.email})` : "";
    return `${first} ${last}${email}`.trim();
  }
  return item.name || item.id;
}

export function useOrgEntities(orgId: string | undefined, assignType: AssignType | undefined) {
  const entityKey = assignType ? ENTITY_TYPE_MAP[assignType] : undefined;
  const enabled = Boolean(orgId && entityKey);

  const { data, isLoading } = useQuery({
    queryKey: ["org", orgId, entityKey],
    queryFn: async () => {
      const items = await api.get<OrgEntityRaw[]>(`/api/orgs/${orgId}/${entityKey}`);
      return items.map((item) => ({
        id: item.id,
        label: formatLabel(item, entityKey!),
      }));
    },
    enabled,
    staleTime: 30_000,
  });

  return {
    options: (data ?? []) as OrgEntity[],
    isLoading: enabled && isLoading,
  };
}
