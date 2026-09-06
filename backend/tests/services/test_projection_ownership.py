"""Row scoping is declared in the Blueprint, not inferred from column names.

``security.ownershipRules`` is what decides whether one signed-in user can read
another's rows. These tests pin two things: that an object rule becomes a real
predicate the data engine can apply, and that a prose rule — or no rule — leaves
an entity unscoped rather than guessing. The second half matters as much as the
first: an ATS records ``postedByUserId`` for the audit trail while every
recruiter is meant to see every role, so a projection that scoped on
owner-shaped column names would break correct applications.
"""
import json
from pathlib import Path

from services.blueprint.projection import (
    ownership_rules,
    project_ownership_rules,
    render_ownership_rules_module,
)

RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime"


def doc(rules, entities=None):
    return {
        "data": {"entities": entities or [
            {"id": "ENTITY-001", "name": "Invoice", "table": "invoices",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "ownerId", "type": "uuid"}]},
            {"id": "ENTITY-002", "name": "Announcement", "table": "announcements",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]},
        ]},
        "security": {"ownershipRules": rules},
    }


def test_an_object_rule_becomes_an_enforceable_predicate():
    m = ownership_rules(doc([
        {"entity": "Invoice", "column": "ownerId", "unscopedRoles": ["admin"]},
    ]))
    assert m["invoice"] == [
        {"column": "ownerId", "kind": "scope", "scope": "user",
         "unscopedRoles": ["admin"]}
    ]


def test_an_attribution_rule_is_projected_as_fill_only():
    # `createdByUserId` is who acted, not who may look. The engine reads `kind`
    # to decide whether the column also gates reads.
    m = ownership_rules(doc([
        {"entity": "Invoice", "column": "createdByUserId", "kind": "attribution"},
    ]))
    assert m["invoice"][0]["kind"] == "attribution"


def test_kind_defaults_to_scope_so_an_omission_is_not_a_hole():
    m = ownership_rules(doc([{"entity": "Invoice", "column": "ownerId"}]))
    assert m["invoice"][0]["kind"] == "scope"


def test_a_prose_rule_documents_policy_and_scopes_nothing():
    # The distinction is the whole point: prose is what every live Blueprint
    # holds today, and treating it as enforcement would mean parsing English
    # to decide who sees what.
    m = ownership_rules(doc([
        "An invoice may be read only by the user who raised it.",
    ]))
    assert m == {}


def test_an_entity_with_no_rule_is_projected_unscoped():
    m = ownership_rules(doc([
        {"entity": "Invoice", "column": "ownerId"},
    ]))
    assert "announcement" not in m and "announcements" not in m


def test_only_scope_rules_reach_the_where_clause():
    src = (RUNTIME / "data-engine.ts").read_text()
    # scopeConditions drops attribution rules before building any predicate.
    assert 'r.kind !== "attribution"' in src
    # create() fills from EVERY rule — the fill is what both kinds share.
    assert "for (const rule of ownershipRulesFor(entityName)) {" in src


def test_a_plural_entity_name_does_not_emit_a_junk_singular():
    # `roles` -> `rol` and `candidates` -> `candidat` were keys nothing asks
    # for and one more way a rule could land on the wrong entity.
    m = ownership_rules(doc([{"entity": "Role", "column": "postedByUserId"}], entities=[
        {"id": "ENTITY-001", "name": "Role", "table": "roles", "fields": []},
    ]))
    assert set(m) == {"role", "roles"}


def test_a_sibilant_plural_still_singularises():
    m = ownership_rules(doc([{"entity": "Class", "column": "ownerId"}], entities=[
        {"id": "ENTITY-001", "name": "Class", "table": "classes", "fields": []},
    ]))
    assert "class" in m and "classes" in m


def test_scope_defaults_to_the_acting_user():
    m = ownership_rules(doc([{"entity": "Invoice", "column": "ownerId"}]))
    assert m["invoice"][0]["scope"] == "user"


def test_a_workspace_rule_survives_projection():
    m = ownership_rules(doc([
        {"entity": "Invoice", "column": "workspaceId", "scope": "workspace"},
    ]))
    assert m["invoice"][0] == {
        "column": "workspaceId", "kind": "scope", "scope": "workspace",
        "unscopedRoles": [],
    }


def test_a_rule_is_reachable_by_every_spelling_of_its_entity():
    # The API route asks for the schema export ("invoices"), the server render
    # asks for the Blueprint name ("Invoice"). A rule found by one and missed by
    # the other is an entity that is scoped on one transport and open on the
    # other — which is the bug this manifest exists to close.
    m = ownership_rules(doc([{"entity": "invoices", "column": "ownerId"}]))
    assert m["invoice"] == m["invoices"]


def test_a_rule_naming_an_unknown_entity_is_still_emitted():
    # Dropping it would fail open. Emitted, the runtime fails closed on the
    # missing column and says so.
    m = ownership_rules(doc([{"entity": "Ghost", "column": "ownerId"}]))
    assert "ghost" in m


def test_an_incomplete_rule_is_not_half_applied():
    assert ownership_rules(doc([{"entity": "Invoice"}])) == {}
    assert ownership_rules(doc([{"column": "ownerId"}])) == {}


def test_the_manifest_is_written_even_when_empty(tmp_path):
    # The data engine imports it statically. A missing file must be a compile
    # error, never an app that silently stops scoping.
    project_ownership_rules(doc([]), tmp_path)
    src = (tmp_path / "src" / "lib" / "ownership-rules.ts").read_text()
    assert "export const OWNERSHIP_RULES" in src
    assert "export function ownershipRulesFor" in src


def test_projection_is_byte_identical_on_a_re_run(tmp_path):
    d = doc([{"entity": "Invoice", "column": "ownerId", "unscopedRoles": ["admin"]}])
    project_ownership_rules(d, tmp_path)
    first = (tmp_path / "src" / "lib" / "ownership-rules.ts").read_text()
    project_ownership_rules(d, tmp_path)
    assert (tmp_path / "src" / "lib" / "ownership-rules.ts").read_text() == first


def test_both_pipelines_render_the_same_module():
    # schema_builder emits this file too. Two renderings of the same lookup are
    # two things that drift; the legacy path calls the same renderer.
    from services import schema_builder

    assert "render_ownership_rules_module" in Path(
        schema_builder.__file__).read_text()


def test_the_data_engine_reads_the_manifest():
    src = (RUNTIME / "data-engine.ts").read_text()
    assert 'from "./ownership-rules"' in src
    assert "ownershipRulesFor" in src


def test_every_read_path_applies_the_scope():
    # The data engine is the chokepoint: the API route and the server render
    # both call these directly, so a control anywhere else would miss one.
    src = (RUNTIME / "data-engine.ts").read_text()
    for fn in ("create", "query", "findById", "stats", "update", "remove"):
        assert f"export async function {fn}(" in src
    # The predicate is applied, not merely defined. Call sites go through
    # accessConditions, which folds the declared and the authored halves
    # together — see test_both_halves_land_in_one_where.
    assert src.count("accessConditions(") >= 9


def test_the_route_hands_stats_the_same_context_as_the_list():
    route = (Path(__file__).resolve().parents[2]
             / "templates" / "data-api-route.ts").read_text()
    assert "stats(entity, ctx)" in route


def test_the_server_render_hands_the_actor_to_aggregates_and_charts():
    page = (Path(__file__).resolve().parents[2] / "templates" / "app-foundation"
            / "src" / "lib" / "schema-page.tsx").read_text()
    assert "resolveAggregate(s as any, engineCtx)" in page
    assert "resolveSeries(s as any, engineCtx)" in page


def test_the_fixture_blueprint_matches_the_contract():
    # The runtime test's fixture is a Blueprint fragment; if the contract moves
    # under it, the node test would be scoping against a shape nothing emits.
    fixture = json.loads(
        (RUNTIME / "__tests__" / "ownership-fixture.blueprint.json").read_text())
    contract = json.loads(
        (Path(__file__).resolve().parents[2]
         / "contracts" / "blueprint.schema.json").read_text())
    item = (contract["properties"]["security"]["properties"]
            ["ownershipRules"]["items"])
    # `z.union` is emitted as `anyOf` by the schema emitter — the JSON contract
    # is generated from the TypeScript source and that is the keyword it
    # writes. This read `oneOf`, which existed only in a copy of the JSON that
    # had drifted from its source; regenerating removed it and the test failed
    # against the very file it is meant to check.
    variants = item.get("oneOf") or item.get("anyOf") or []
    obj = next(o for o in variants if o.get("type") == "object")
    allowed = set(obj["properties"])
    for rule in fixture["security"]["ownershipRules"]:
        if isinstance(rule, dict):
            assert set(rule) <= allowed
            assert set(obj["required"]) <= set(rule)


# ── the live blueprint ─────────────────────────────────────────────────────

ATS = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"


def _ats():
    return json.loads(ATS.read_text())


def test_ats_declares_every_actor_column_it_says_it_fills():
    # security.ownershipRules states in prose that six actor columns are set
    # server-side and ignored if present in a request body. Nothing enforced
    # that until the columns were declared as rules, so this pins the pair.
    m = ownership_rules(_ats())
    declared = {(k, r["column"]) for k, rules in m.items() for r in rules}
    for entity, column in [
        ("role", "postedByUserId"),
        ("candidate", "createdByUserId"),
        ("candidatedocument", "uploadedByUserId"),
        ("application", "createdByUserId"),
        ("applicationstageevent", "changedByUserId"),
        ("interview", "scheduledByUserId"),
        ("offerdecision", "decidedByUserId"),
    ]:
        assert (entity, column) in declared, f"{entity}.{column} not declared"


def test_ats_scopes_no_reads_because_it_says_authorisation_is_by_role():
    # TEST-059 (tests/permissions/recruiter_scope_unfiltered.test.ts) asserts a
    # recruiter sees rows another recruiter created. A single kind:"scope" rule
    # on an attribution column would break it, silently, for every list, detail
    # route, KPI tile and chart at once.
    m = ownership_rules(_ats())
    scoping = [(k, r) for k, rules in m.items() for r in rules
               if r["kind"] != "attribution"]
    assert scoping == [], f"ats-live must not scope reads: {scoping}"


def test_ats_does_not_fill_the_interviewer_domain_fk():
    # Interview carries scheduledByUserId (who booked it) AND interviewerUserId
    # (who conducts it). Only the first is the actor. Filling the second from
    # the session would quietly reassign every interview to its booker.
    m = ownership_rules(_ats())
    cols = {r["column"] for rules in m.values() for r in rules}
    assert "scheduledByUserId" in cols
    assert "interviewerUserId" not in cols


# ── row_access: the configurable half ──────────────────────────────────────


def test_row_access_is_a_rule_type_the_api_accepts():
    # Without this the builder cannot save one and the API rejects it, so the
    # whole configurable half is unreachable.
    from routers.rules import VALID_RULE_TYPES

    assert "row_access" in VALID_RULE_TYPES

    from services.runtime_injector import _SYNC_VALID_RULE_TYPES

    assert "row_access" in _SYNC_VALID_RULE_TYPES, (
        "the sync helper keeps its own copy of the list; a rule type missing "
        "from it is dropped on the way into the DB"
    )


def test_the_runtime_declares_the_rule_type_and_its_config():
    types = (RUNTIME / "rules" / "types.ts").read_text()
    assert '| "row_access"' in types
    assert "RowAccessRuleConfig" in types
    # Named for the convention condition_action already set, not a new one.
    assert "whenFeel" in types


def test_the_rules_engine_exposes_row_rules_without_evaluating_them():
    engine = (RUNTIME / "rules" / "engine.ts").read_text()
    assert "export async function rowAccessRulesFor(" in engine
    index = (RUNTIME / "rules" / "index.ts").read_text()
    assert "rowAccessRulesFor" in index, "not exported = not reachable from the data engine"


def test_a_row_rule_is_compiled_to_sql_not_applied_per_row():
    # The distinction is the point: a row removed after the query still counted
    # towards total, still paged, and still summed into every aggregate.
    compiler = (RUNTIME / "rules" / "row-access-sql.ts").read_text()
    assert "export function compileRowAccess(" in compiler
    for op in ("inArray", "isNull", "isNotNull", "gte", "lte"):
        assert op in compiler, f"{op} is not compiled"
    engine = (RUNTIME / "data-engine.ts").read_text()
    assert "compileRowAccess" in engine
    assert "async function rowAccessConditions(" in engine


def test_both_halves_land_in_one_where():
    # A declared ownership column and an authored row rule have to end up in
    # the same predicate, or one of them is not in the count.
    src = (RUNTIME / "data-engine.ts").read_text()
    assert "async function accessConditions(" in src
    assert "...scopeConditions(entityName, entity, ctx)," in src
    assert "await rowAccessConditions(entityName, entity, ctx)" in src
    # Every read and write path goes through the combined form.
    assert src.count("accessConditions(") >= 9


def test_an_uncompilable_rule_returns_no_rows():
    src = (RUNTIME / "data-engine.ts").read_text()
    where = src[src.index("async function rowAccessConditions("):]
    where = where[: where.index("async function accessConditions(")]
    assert "cannot be enforced" in where
    assert "sql`false`" in where


def test_the_builder_offers_the_new_type():
    types = (Path(__file__).resolve().parents[3]
             / "frontend" / "src" / "types" / "rules.ts").read_text()
    assert '| "row_access"' in types
    assert '{ value: "row_access", label: "Row Access" }' in types
    assert "whenFeel" in types
