/**
 * Which ownership rules a role is held to (found building a food-delivery app: an order is a customer's, a restaurant's and a driver's,
 * and the engine ANDed every rule of an entity, so no one could reach any order). Self-contained: it imports only the pure module.
 */
import { appliesTo, reachesNothing } from "../ownership-roles.ts";

let failed = 0;
const ok = (c: unknown, what: string) => { console.log(`  ${c ? "ok  " : "FAIL"} ${what}`); if (!c) failed += 1; };

const customer = { column: "customerId", roles: ["Customer"], unscopedRoles: ["Admin"] };
const restaurant = { column: "restaurantId", roles: ["Restaurant Manager"], unscopedRoles: ["Admin"] };
const driver = { column: "driverId", roles: ["Delivery Partner"], unscopedRoles: ["Admin"] };
const everyone = { column: "createdBy" };
const orderRules = [customer, restaurant, driver];

console.log("a rule applies to the roles it names");
ok(appliesTo(customer, "Customer"), "the customer rule applies to a customer");
ok(!appliesTo(customer, "Restaurant Manager"), "and not to a restaurant manager");
ok(!appliesTo(customer, undefined) && !appliesTo(customer, null), "and not to nobody");
ok(appliesTo(everyone, "Anything") && appliesTo(everyone, undefined), "a rule that names no roles applies to everyone, as before");
ok(appliesTo({ roles: [] }, "Customer"), "an empty list is the same as none");

console.log("a person in none of the roles reaches nothing");
ok(!reachesNothing(orderRules, "Customer"), "a customer is addressed");
ok(!reachesNothing(orderRules, "Delivery Partner"), "a driver is addressed");
ok(!reachesNothing(orderRules, "Admin"), "the exempt role is not shut out");
ok(reachesNothing(orderRules, "Support Agent"), "a role no rule names, and no rule exempts, reaches no order");
ok(reachesNothing(orderRules, undefined) && reachesNothing(orderRules, null), "someone with no role reaches none");
ok(!reachesNothing([everyone], "Anything"), "an entity whose rules name no roles is never shut out by this");
ok(!reachesNothing([], "Customer"), "an entity with no rules is never shut out by this");
ok(reachesNothing([everyone, customer], "Restaurant Manager"), "one role-addressed rule beside a general one still shuts out a role it does not name");

console.log("each person is held to exactly their own rule");
const mine = (role: string) => orderRules.filter((r) => appliesTo(r, role)).map((r) => r.column);
ok(JSON.stringify(mine("Customer")) === '["customerId"]', "a customer: customerId only");
ok(JSON.stringify(mine("Restaurant Manager")) === '["restaurantId"]', "a restaurant manager: restaurantId only");
ok(JSON.stringify(mine("Delivery Partner")) === '["driverId"]', "a delivery partner: driverId only");

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log("\nall passed");
