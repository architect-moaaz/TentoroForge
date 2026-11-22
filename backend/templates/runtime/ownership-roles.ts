/**
 * Which ownership rules a person's role is held to.
 *
 * One entity is often reached differently by different roles: in a food-delivery app an order is a customer's (by
 * `customerId`), a restaurant's (by `restaurantId`) and the driver's who carries it (by `driverId`). A rule that names `roles`
 * applies only to people holding one of them, so those three are three rules on one entity, each for its own role.
 *
 * The rules are applied to a person as follows. A rule that names no `roles` applies to everyone, as before. A rule with `roles`
 * applies to the people who hold one of them. A person who holds NONE of the roles any such rule names, and is exempt from none
 * of them (`unscopedRoles`), reaches NOTHING: a role left out is never handed every row by having been left out.
 *
 * Pure: no imports, so it is tested alone. Used by the data engine (`data-engine.ts`).
 *
 * Forge runtime — do not remove.
 */

export interface RoleAddressed {
  roles?: string[];
  unscopedRoles?: string[];
}

/** True when the rule applies to a person holding `role` (a rule with no `roles` applies to everyone). */
export function appliesTo(rule: RoleAddressed, role: string | undefined | null): boolean {
  const roles = rule.roles ?? [];
  if (roles.length === 0) return true;
  return !!role && roles.includes(role);
}

/**
 * True when the entity's rules address roles, and this person is in none of them and exempt from none: they reach no rows.
 * An entity whose rules name no roles is never "nothing" by this test.
 */
export function reachesNothing(rules: RoleAddressed[], role: string | undefined | null): boolean {
  const addressed = rules.filter((r) => (r.roles ?? []).length > 0);
  if (addressed.length === 0) return false;
  if (!role) return true;
  return !addressed.some((r) => (r.roles ?? []).includes(role) || (r.unscopedRoles ?? []).includes(role));
}
