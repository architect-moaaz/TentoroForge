"""Tests for interaction_spec — the validator both Smith and the editor
call before writing a field's ``interaction`` block."""

from __future__ import annotations

import pytest

from services.interaction_spec import (
    KNOWN_FUNCTIONS,
    ValidationResult,
    extract_formula_refs,
    validate_interaction,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def _employee_form() -> tuple[dict, list[dict]]:
    """A simple new-employee form: basicSalary + hra + da + net + country."""
    fields = [
        {"name": "basicSalary", "kind": "number"},
        {"name": "hra", "kind": "number"},
        {"name": "da", "kind": "number"},
        {"name": "net", "kind": "number"},
        {"name": "country", "kind": "select"},
        {"name": "state", "kind": "select"},
    ]
    return fields[1], fields  # target: hra


def _registry_with_states() -> dict:
    """Registry with a states resource so cascade tests can hit real slugs."""
    return {
        "entities": {
            "State": {
                "slug": "states",
                "columns": [
                    {"name": "id"},
                    {"name": "name"},
                    {"name": "countryId"},
                ],
            },
            "Country": {
                "slug": "countries",
                "columns": [{"name": "id"}, {"name": "name"}, {"name": "code"}],
            },
            "Customer": {
                "slug": "customers",
                "columns": [
                    {"name": "id"},
                    {"name": "name"},
                    {"name": "address"},
                    {"name": "phone"},
                    {"name": "tier"},
                ],
            },
        }
    }


# ── Basic shape ───────────────────────────────────────────────────────────


class TestShape:
    def test_non_dict_rejected(self):
        r = validate_interaction("not a dict", {"name": "x"}, [])
        assert not r.ok
        assert "must be a JSON object" in r.errors[0]

    def test_empty_dict_is_ok_but_canonical_empty(self):
        r = validate_interaction({}, {"name": "hra"}, [])
        assert r.ok
        assert r.canonical == {}

    def test_unknown_top_level_key_rejected(self):
        r = validate_interaction(
            {"comptued": {"formula": "1+1"}},  # typo
            {"name": "hra"},
            [],
        )
        assert not r.ok
        assert any("unknown interaction key 'comptued'" in e for e in r.errors)
        # Should suggest the typo fix
        assert any("computed" in e for e in r.errors)


# ── ComputedInteraction ───────────────────────────────────────────────────


class TestComputed:
    def test_valid_computed(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"computed": {"formula": "basicSalary * 0.4"}},
            field,
            siblings,
        )
        assert r.ok, r.errors
        assert r.canonical["computed"]["formula"] == "basicSalary * 0.4"
        assert r.canonical["computed"]["readOnly"] is True  # default
        assert r.canonical["dependsOn"] == ["basicSalary"]  # auto-derived

    def test_computed_with_helper_function(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"computed": {"formula": "round(basicSalary * 0.4, 2)"}},
            field,
            siblings,
        )
        assert r.ok, r.errors
        assert "basicSalary" in r.canonical["dependsOn"]

    def test_computed_missing_formula(self):
        r = validate_interaction({"computed": {}}, {"name": "hra"}, [])
        assert not r.ok
        assert "missing 'formula'" in r.errors[0]

    def test_computed_empty_formula(self):
        r = validate_interaction(
            {"computed": {"formula": "   "}}, {"name": "hra"}, []
        )
        assert not r.ok
        assert "non-empty string" in r.errors[0]

    def test_computed_unknown_function_suggests(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"computed": {"formula": "rond(basicSalary * 0.4)"}},  # typo
            field,
            siblings,
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "unknown function 'rond'" in joined
        # Should suggest 'round'
        assert "round" in joined

    def test_computed_unknown_sibling_suggests(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"computed": {"formula": "basicSalery * 0.4"}},  # typo
            field,
            siblings,
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "unknown field 'basicSalery'" in joined
        assert "basicSalary" in joined  # suggestion

    def test_computed_self_reference_rejected(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"computed": {"formula": "hra + 100"}},
            field,
            siblings,
        )
        assert not r.ok
        assert any("references itself" in e for e in r.errors)

    def test_computed_explicit_readonly_false_preserved(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"computed": {"formula": "basicSalary * 0.4", "readOnly": False}},
            field,
            siblings,
        )
        assert r.ok, r.errors
        assert r.canonical["computed"]["readOnly"] is False

    def test_computed_non_bool_readonly_rejected(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"computed": {"formula": "basicSalary * 0.4", "readOnly": "yes"}},
            field,
            siblings,
        )
        assert not r.ok
        assert any("expected bool" in e for e in r.errors)

    def test_computed_all_new_helper_functions(self):
        """Sanity-check the Slice 1 additions parse cleanly."""
        field = {"name": "displayName"}
        siblings = [
            {"name": "first"}, {"name": "last"}, {"name": "displayName"},
        ]
        r = validate_interaction(
            {"computed": {"formula": "concat(upper(first), ' ', lower(last))"}},
            field,
            siblings,
        )
        assert r.ok, r.errors


# ── OptionsFrom (cascade dropdowns) ───────────────────────────────────────


class TestOptionsFrom:
    def test_valid_cascade(self):
        field = {"name": "state"}
        siblings = [{"name": "country"}, {"name": "state"}]
        r = validate_interaction(
            {
                "optionsFrom": {
                    "source": "states",
                    "value": "id",
                    "label": "name",
                    "filter": {"countryId": "{{country}}"},
                }
            },
            field,
            siblings,
            registry=_registry_with_states(),
        )
        assert r.ok, r.errors
        assert r.canonical["optionsFrom"]["source"] == "states"
        assert r.canonical["dependsOn"] == ["country"]  # auto-derived from filter

    def test_missing_source_rejected(self):
        r = validate_interaction(
            {"optionsFrom": {"value": "id", "label": "name"}},
            {"name": "state"},
            [],
        )
        assert not r.ok
        assert any("optionsFrom.source" in e for e in r.errors)

    def test_unknown_resource_suggests(self):
        r = validate_interaction(
            {"optionsFrom": {"source": "stats", "value": "id", "label": "name"}},
            {"name": "state"},
            [],
            registry=_registry_with_states(),
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "unknown resource 'stats'" in joined
        assert "states" in joined  # suggested

    def test_unknown_column_suggests(self):
        r = validate_interaction(
            {"optionsFrom": {"source": "states", "value": "iid", "label": "name"}},
            {"name": "state"},
            [],
            registry=_registry_with_states(),
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "'iid'" in joined
        assert "id" in joined  # suggested column

    def test_filter_template_unknown_sibling(self):
        r = validate_interaction(
            {
                "optionsFrom": {
                    "source": "states",
                    "value": "id",
                    "label": "name",
                    "filter": {"countryId": "{{contry}}"},  # typo
                }
            },
            {"name": "state"},
            [{"name": "country"}, {"name": "state"}],
            registry=_registry_with_states(),
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "unknown field 'contry'" in joined
        assert "country" in joined

    def test_no_registry_skips_resource_checks(self):
        r = validate_interaction(
            {"optionsFrom": {"source": "whatever", "value": "id", "label": "name"}},
            {"name": "x"},
            [],
            registry=None,
        )
        assert r.ok, r.errors  # resource check skipped when registry absent


# ── OnChange (autofill) ───────────────────────────────────────────────────


class TestOnChange:
    def test_valid_onchange(self):
        field = {"name": "customerId"}
        siblings = [
            {"name": "customerId"}, {"name": "address"}, {"name": "phone"},
        ]
        r = validate_interaction(
            {
                "onChange": {
                    "fetch": {"resource": "customers", "by": "id", "from": "customerId"},
                    "set": {
                        "address": "{{result.address}}",
                        "phone": "{{result.phone}}",
                    },
                }
            },
            field,
            siblings,
            registry=_registry_with_states(),
        )
        assert r.ok, r.errors
        assert r.canonical["onChange"]["fetch"]["resource"] == "customers"

    def test_onchange_set_target_unknown_field(self):
        field = {"name": "customerId"}
        siblings = [{"name": "customerId"}]
        r = validate_interaction(
            {
                "onChange": {
                    "fetch": {"resource": "customers", "by": "id", "from": "customerId"},
                    "set": {"phne": "{{result.phone}}"},  # typo target
                }
            },
            field,
            siblings,
            registry=_registry_with_states(),
        )
        assert not r.ok
        assert any("unknown target field 'phne'" in e for e in r.errors)

    def test_onchange_template_without_result_prefix(self):
        field = {"name": "customerId"}
        siblings = [{"name": "customerId"}, {"name": "address"}]
        r = validate_interaction(
            {
                "onChange": {
                    "fetch": {"resource": "customers", "by": "id", "from": "customerId"},
                    "set": {"address": "{{address}}"},  # missing result. prefix
                }
            },
            field,
            siblings,
            registry=_registry_with_states(),
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "resolve against `result`" in joined

    def test_onchange_unknown_column_warns_not_fails(self):
        field = {"name": "customerId"}
        siblings = [{"name": "customerId"}, {"name": "address"}]
        r = validate_interaction(
            {
                "onChange": {
                    "fetch": {"resource": "customers", "by": "id", "from": "customerId"},
                    "set": {"address": "{{result.adres}}"},  # typo column
                }
            },
            field,
            siblings,
            registry=_registry_with_states(),
        )
        # Column typos are warnings — the runtime tolerates missing keys and
        # the actual column list may drift; we surface as guidance, not block.
        assert r.ok
        joined = " ".join(r.warnings)
        assert "adres" in joined


# ── dependsOn ─────────────────────────────────────────────────────────────


class TestDependsOn:
    def test_explicit_deps_added(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"dependsOn": ["basicSalary", "da"]},
            field,
            siblings,
        )
        assert r.ok
        assert r.canonical["dependsOn"] == ["basicSalary", "da"]

    def test_unknown_dep_suggests(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"dependsOn": ["basicSalery"]},  # typo
            field,
            siblings,
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "basicSalary" in joined  # suggestion

    def test_self_ref_in_depends_dropped_not_failed(self):
        field, siblings = _employee_form()
        r = validate_interaction(
            {"dependsOn": ["hra", "basicSalary"]},
            field,
            siblings,
        )
        assert r.ok
        assert "hra" not in r.canonical["dependsOn"]
        assert any("refers to the field itself" in w for w in r.warnings)

    def test_user_deps_merged_with_derived(self):
        field, siblings = _employee_form()
        # formula only refers to basicSalary; user adds da manually
        r = validate_interaction(
            {
                "computed": {"formula": "basicSalary * 0.4"},
                "dependsOn": ["da"],
            },
            field,
            siblings,
        )
        assert r.ok
        assert set(r.canonical["dependsOn"]) == {"basicSalary", "da"}


# ── Predicates (visibleIf/requiredIf/etc.) ────────────────────────────────


class TestPredicates:
    def test_valid_visible_if(self):
        r = validate_interaction(
            {"visibleIf": "country == 'US'"},
            {"name": "state"},
            [{"name": "state"}, {"name": "country"}],
        )
        assert r.ok, r.errors
        assert r.canonical["visibleIf"] == "country == 'US'"
        assert r.canonical["dependsOn"] == ["country"]

    def test_all_four_predicate_kinds(self):
        for kind in ("visibleIf", "requiredIf", "enabledIf", "readOnlyIf"):
            r = validate_interaction(
                {kind: "type == 'company'"},
                {"name": "companyName"},
                [{"name": "companyName"}, {"name": "type"}],
            )
            assert r.ok, f"{kind}: {r.errors}"
            assert r.canonical[kind] == "type == 'company'"

    def test_predicate_unknown_field(self):
        r = validate_interaction(
            {"visibleIf": "cuntry == 'US'"},  # typo
            {"name": "state"},
            [{"name": "state"}, {"name": "country"}],
        )
        assert not r.ok
        joined = " ".join(r.errors)
        assert "unknown field 'cuntry'" in joined

    def test_predicate_no_operator_warns(self):
        r = validate_interaction(
            {"visibleIf": "isCompany"},  # no comparison
            {"name": "companyName"},
            [{"name": "companyName"}, {"name": "isCompany"}],
        )
        # Valid but warns — feel-lite will evaluate truthiness.
        assert r.ok
        assert any("no comparison operator" in w for w in r.warnings)

    def test_predicate_empty_rejected(self):
        r = validate_interaction(
            {"visibleIf": "   "},
            {"name": "x"},
            [{"name": "x"}],
        )
        assert not r.ok


# ── extract_formula_refs helper ───────────────────────────────────────────


class TestExtractRefs:
    def test_simple_arithmetic(self):
        idents, funcs = extract_formula_refs("a + b * c")
        assert idents == {"a", "b", "c"}
        assert funcs == set()

    def test_function_call(self):
        idents, funcs = extract_formula_refs("round(price * qty, 2)")
        assert idents == {"price", "qty"}
        assert funcs == {"round"}

    def test_nested_functions(self):
        idents, funcs = extract_formula_refs("sum(a, min(b, c), max(d, 5))")
        assert idents == {"a", "b", "c", "d"}
        assert funcs == {"sum", "min", "max"}

    def test_reserved_idents_excluded(self):
        idents, funcs = extract_formula_refs("ifElse(active == true, x, null)")
        assert idents == {"active", "x"}  # true, null excluded
        assert funcs == {"ifElse"}

    def test_string_and_num_literals_ignored(self):
        idents, funcs = extract_formula_refs('concat(first, " ", last, "-", 42)')
        assert idents == {"first", "last"}
        assert funcs == {"concat"}

    def test_non_string_returns_empty(self):
        assert extract_formula_refs(None) == (set(), set())
        assert extract_formula_refs(123) == (set(), set())


# ── KNOWN_FUNCTIONS coverage ──────────────────────────────────────────────


class TestKnownFunctions:
    def test_baseline_functions_present(self):
        for fn in ("daysBetween", "sum", "min", "max", "round", "ifElse"):
            assert fn in KNOWN_FUNCTIONS

    def test_slice1_additions_present(self):
        for fn in ("concat", "upper", "lower", "age", "now", "formatCurrency"):
            assert fn in KNOWN_FUNCTIONS, f"Slice 1 helper '{fn}' missing"
