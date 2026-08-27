import { useAuthStore } from "@/stores/auth";

interface UserLike {
  orgs?: { org_id: string; role: string }[];
}

/** True when the user is an owner or admin of the given org. */
export function isOrgAdmin(user: UserLike | null | undefined, orgId: string): boolean {
  return !!user?.orgs?.some(
    (o) => o.org_id === orgId && (o.role === "owner" || o.role === "admin"),
  );
}

/** Hook form, reads the current user from the auth store. */
export function useIsOrgAdmin(orgId: string): boolean {
  const user = useAuthStore((s) => s.user);
  return isOrgAdmin(user, orgId);
}
