"""Each role sees only its own rows — proven as two different people.

`security.ownershipRules` declares which column scopes a record to the
person who owns it (`kind: "scope"`), and the data engine adds that
predicate to every read. Nothing measured that the built application keeps
to it: a demoted rule (prose where an object was meant) let every vendor
see every other vendor's products and orders, and nobody noticed until a
tester did (Ecom L1, 2026-10-11).

For each scoped record type and each role the rule applies to, the list
endpoint is read as two people of that role: what each gets must be theirs
(the scope column holds their own id), the two sets must not overlap, and
the first person's count must equal what the database holds for them. A
role the rule exempts (`unscopedRoles`) must get every row. HTTP and SQL
only, no model. A record type with no rows for either person cannot be
proven either way and is `untried`.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)

LIMIT = 200


def scoped_entities(doc: dict) -> list[tuple[dict, list[dict]]]:
    """`(entity, scope rules)` for every live record type with a scope rule."""
    from services.blueprint.projection import _key_forms, ownership_rules
    manifest = ownership_rules(doc)
    out: list[tuple[dict, list[dict]]] = []
    for e in (doc.get("data") or {}).get("entities") or []:
        if not isinstance(e, dict) or e.get("status") == "DEPRECATED" or not e.get("name"):
            continue
        rules: list[dict] = []
        for form in _key_forms(str(e["name"])):
            for r in manifest.get(form) or []:
                if r.get("kind") == "scope" and r not in rules:
                    rules.append(r)
        if rules:
            out.append((e, rules))
    return out


def people_of_role(app: Any, doc: dict, role: str) -> list[tuple[str, str]]:
    """Up to two `(id, name)` logins of `role` on the copy, the seeded
    administrator aside — REAL ones only. A session for a person the users
    table has never seen is answered 404 by the data API ("No record with
    that id"), which proves nothing about the scope; a role with fewer than
    two logins is `untried`, said so, never red (rwt6ef5p, 2026-10-11)."""
    from services.blueprint.page_review import _query
    from services.seed_backstop import _ADMIN_UUID
    cols = {r[0] for r in _query(app, "select column_name from information_schema.columns "
                                     "where table_name = 'users'") if r}
    by = [c for c in ("role", "account_type") if c in cols]
    name = next((c for c in ("name", "email") if c in cols), "id")
    people: list[tuple[str, str]] = []
    if by:
        safe = role.replace("'", "''")
        where = " or ".join(f"{c} = '{safe}'" for c in by)
        order = "order by created_at " if "created_at" in cols else ""
        rows = _query(app, f"select id, {name} from users where ({where}) and id <> '{_ADMIN_UUID}' {order}limit 2")
        people = [(r[0], r[1] if len(r) > 1 else role) for r in rows or [] if r and r[0]]
        if not people:
            # A ONE-ROLE APPLICATION'S ADMINISTRATOR IS ONE OF ITS PEOPLE. Its
            # only role is the administrator's too, so the seed makes no other
            # login of it, and every scoped record type of Personal Finance
            # went untried (u8w3uw4j, 2026-10-21). The administrator holding
            # the role is the first person; the second is made from them.
            rows = _query(app, f"select id, {name} from users where ({where}) and id = '{_ADMIN_UUID}' limit 1")
            people = [(r[0], r[1] if len(r) > 1 else role) for r in rows or [] if r and r[0]]
    if len(people) == 1:
        made = second_person(app, people[0])
        if made:
            people.append(made)
    return people[:2]


def people_in_two_organisations(app: Any, doc: dict, role: str) -> list[tuple[str, str]]:
    """Two logins of `role`, each the member of a DIFFERENT organisation (the
    seed makes one per role in each of two), as `(id, name)`; fewer when the
    copy has fewer."""
    from services.blueprint.page_review import _query
    safe = role.replace("'", "''")
    rows = _query(app, "select u.id, coalesce(u.name, u.email), m.org_id from users u "
                       "join forge_memberships m on m.user_id = u.id::text and m.status = 'active' "
                       f"where m.role = '{safe}' order by m.org_id, u.created_at")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for r in rows or []:
        if len(r) < 3 or r[2] in seen:
            continue
        seen.add(r[2])
        out.append((r[0], r[1]))
        if len(out) == 2:
            break
    return out


def second_person(app: Any, first: tuple[str, str]) -> tuple[str, str] | None:
    """A second login of the same role, made on the copy from the first: the
    same row with a fresh id and address. The seed makes one person per role
    and the copy is thrown away, so the check makes the other itself rather
    than leave every scoped record type untried (rwt6ef5p, 2026-10-11)."""
    import uuid
    from services.blueprint.page_review import _query
    cols = [r[0] for r in _query(app, "select column_name from information_schema.columns "
                                      "where table_name = 'users' order by ordinal_position") if r]
    if "id" not in cols:
        return None
    new_id = str(uuid.uuid4())
    picks = []
    for c in cols:
        if c == "id":
            picks.append(f"'{new_id}'")
        elif c == "email":
            picks.append(f"regexp_replace(email::text, '@', '+second@')")
        elif c == "name":
            picks.append("name::text || ' (second)'")
        else:
            picks.append(f'"{c}"')
    quoted = ", ".join(f'"{c}"' for c in cols)
    first_id = str(first[0]).replace("'", "''")
    _query(app, f'insert into users ({quoted}) select {", ".join(picks)} from users where id::text = \'{first_id}\'')
    made = _query(app, f"select id from users where id::text = '{new_id}'")
    if not made or not made[0]:
        return None
    return new_id, f"{first[1]} (second)"


def _jar(app: Any, role: str, person: tuple[str, str]) -> list[dict]:
    from services.preview_session import Session, cookies
    who = Session(sub=person[0], name=person[1], email=f"{role.lower().replace(' ', '.')}@example.com", role=role)
    return cookies(who, base_url=app.base)


def _rows(app: Any, slug: str, jar: list[dict]) -> tuple[int, list[dict]]:
    import json
    from services.smith.trials import _http
    status, _loc, body = _http(app, "GET", f"/api/data/{slug}?limit={LIMIT}", None, jar)
    if status != 200:
        return int(status), []
    try:
        parsed = json.loads(body)
    except ValueError:
        return int(status), []
    rows = parsed.get("data") if isinstance(parsed, dict) else parsed
    if isinstance(parsed, dict) and rows is None:
        rows = parsed.get("items") or parsed.get("rows") or []
    return int(status), [r for r in rows or [] if isinstance(r, dict)]


def _value(row: dict, column: str) -> str:
    from services.blueprint.projection import to_snake
    for key in (column, to_snake(column)):
        if key in row:
            return str(row.get(key) if row.get(key) is not None else "")
    return ""


def exempt_roles(doc: dict, rule: dict, hops: int = 3) -> set[str]:
    """The roles a rule exempts — along its `through` chain too: the engine
    scopes a reached record by the target's rules, so a role the target
    exempts sees every row here (`throughConditions`)."""
    from services.blueprint.projection import _key_forms, ownership_rules, to_snake
    manifest = ownership_rules(doc)
    out = {str(r) for r in rule.get("unscopedRoles") or []}
    seen: set[str] = set()
    target = str(rule.get("through") or "")
    while target and hops > 0 and target not in seen:
        seen.add(target)
        hops -= 1
        rules = [r for form in _key_forms(target) for r in manifest.get(form) or [] if r.get("kind") == "scope"]
        if not rules:
            break
        for r in rules:
            out |= {str(x) for x in r.get("unscopedRoles") or []}
        target = str(rules[0].get("through") or "")
    return out


def check_access(app: Any, doc: dict, *, only: set[str] | None = None,
                 cancelled: Callable[[], bool] = lambda: False) -> dict:
    """`{total, green, red, untried}` over (record type × role) for every
    scoped record type; `only` names entity ids to check again."""
    from services.blueprint.api_derivation import _slug
    from services.blueprint.page_review import _query
    from services.blueprint.projection import to_snake

    roles = [str(r.get("name")) for r in doc.get("roles") or []
             if isinstance(r, dict) and r.get("name") and r.get("status") != "DEPRECATED"]
    people: dict[str, list[tuple[str, str]]] = {}
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    total = 0
    for entity, rules in scoped_entities(doc):
        eid, ename = str(entity.get("id")), str(entity.get("name"))
        if only is not None and eid not in only:
            continue
        table = str(entity.get("table") or to_snake(ename))
        slug = _slug(ename)
        for rule in rules:
            column = str(rule.get("column") or "")
            exempt = exempt_roles(doc, rule)
            for role in roles:
                total += 1
                label = f"{ename} as {role}"
                it = lambda why: item(f"{eid}:{role}", label, why, eid)  # noqa: E731
                if cancelled():
                    untried.append(it("stopped by the person"))
                    continue
                try:
                    if role not in people:
                        # AN ORGANISATION'S SCOPE IS PROVEN AS TWO ORGANISATIONS:
                        # one member of each, reading the same record type.
                        people[role] = (people_in_two_organisations(app, doc, role)
                                        if str(rule.get("derived") or "") == "tenancy" else [])
                        if len(people[role]) < 2:
                            people[role] = people_of_role(app, doc, role)
                    found = people[role]
                    if len(found) < (1 if role in exempt else 2):
                        untried.append(it(f"no {'login' if role in exempt else 'two logins'} of {role} on the copy to read as"))
                        continue
                    a, b = found[0], (found[1] if len(found) > 1 else found[0])
                    status_a, rows_a = _rows(app, slug, _jar(app, role, a))
                    status_b, rows_b = _rows(app, slug, _jar(app, role, b))
                except Exception as exc:  # noqa: BLE001 — the app did not answer
                    untried.append(it(f"the app did not answer: {str(exc)[:160]}"))
                    continue
                if status_a in (401, 403, 404) and status_b in (401, 403, 404):
                    total -= 1                                   # not this role's record type at all
                    continue
                if status_a != 200 or status_b != 200:
                    red.append(it(f"the list answers HTTP {status_a if status_a != 200 else status_b} to a {role}"))
                    continue
                all_rows = _query(app, f'select count(*) from "{table}"')
                table_count = int(all_rows[0][0]) if all_rows and all_rows[0] and str(all_rows[0][0]).isdigit() else None
                if role in exempt:
                    if table_count is None or table_count > LIMIT:
                        untried.append(it("could not count the table"))
                    elif len(rows_a) == table_count:
                        green.append(it(f"sees every {ename} record, as the rule exempts {role}"))
                    else:
                        red.append(it(f"a {role} is exempt from the {ename} scope but gets {len(rows_a)} of {table_count}"))
                    continue
                if not rows_a and not rows_b:
                    untried.append(it(f"no {ename} records belong to either {role} on the copy"))
                    continue
                ids_a = {str(r.get("id")) for r in rows_a}
                ids_b = {str(r.get("id")) for r in rows_b}
                shared = ids_a & ids_b
                if shared and not rule.get("through"):
                    red.append(it(f"two different {role}s both get {ename} {sorted(shared)[0]} — the scope does not hold"))
                    continue
                if shared:
                    red.append(it(f"two different {role}s both get {len(shared)} {ename} records owned through "
                                  f"{rule.get('through')}"))
                    continue
                if str(rule.get("derived") or "") == "tenancy":
                    orgs = {_value(r, column) for r in rows_a}
                    if len(orgs) > 1:
                        red.append(it(f"a {role} gets {ename} records of {len(orgs)} organisations — the organisation's scope does not hold"))
                        continue
                if not rule.get("through") and rule.get("scope", "user") == "user" and not rule.get("actorColumn"):
                    foreign = [r for r in rows_a if _value(r, column) not in ("", a[0])]
                    if foreign:
                        red.append(it(f"a {role} gets a {ename} record whose {column} is someone else's"))
                        continue
                    col = to_snake(column)
                    own = _query(app, f'select count(*) from "{table}" where "{col}"::text = \'{a[0]}\'')
                    mine = int(own[0][0]) if own and own[0] and str(own[0][0]).isdigit() else None
                    if mine is not None and mine <= LIMIT and mine != len(rows_a):
                        red.append(it(f"a {role} gets {len(rows_a)} {ename} records but owns {mine}"))
                        continue
                green.append(it(f"each {role} gets only their own {ename} records" if str(rule.get("derived") or "") != "tenancy"
                                else f"a {role} gets only their organisation's {ename} records"))
    return {"total": total, "green": green, "red": red, "untried": untried}


__all__ = ["check_access", "exempt_roles", "people_in_two_organisations", "people_of_role", "scoped_entities", "second_person"]
