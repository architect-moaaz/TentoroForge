"""Tests for services.blueprint_coverage — the coverage gate."""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint_coverage import (
    check_coverage,
    check_coverage_from_sources,
    _snake_singularize,
    _snake_to_camel,
    _table_name_variants,
    _strip_uncovered_section,
)
from services.blueprint_builder import build_blueprint, _load_sources
from services.blueprint_writer import write_blueprint


def _write(root: Path, rel: str, content: dict | str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_text(json.dumps(content, indent=2), encoding="utf-8")


class TestEmptyDir:
    def test_missing_dir_returns_empty_100pct(self, tmp_path):
        result = check_coverage(tmp_path / "nope")
        assert result["coverage_pct"] == 100.0
        assert result["covered"] == 0
        assert result["uncovered"]["pages"] == []

    def test_dir_with_nothing_100pct(self, tmp_path):
        result = check_coverage(tmp_path)
        assert result["coverage_pct"] == 100.0


class TestPageCoverage:
    def test_orphan_page_flagged(self, tmp_path):
        # A schema file exists on disk but nothing references it and no
        # BLUEPRINT.md mentions it.
        _write(tmp_path, "src/schemas/orphaned.json", {"title": "Orphan"})
        result = check_coverage(tmp_path)
        pages = result["uncovered"]["pages"]
        assert any("orphaned.json" in p for p in pages), pages

    def test_page_referenced_via_navflow_still_uncovered_without_blueprint(self, tmp_path):
        # Blueprint hasn't been written yet — even a nav-flow reference
        # doesn't make it covered, because coverage searches the
        # blueprint text.
        _write(tmp_path, "src/schemas/dashboard.json", {"title": "Dashboard"})
        _write(tmp_path, "contracts/nav-flow.json", {
            "pages": [{"id": "dash", "route": "/dashboard",
                       "schemaFile": "src/schemas/dashboard.json"}],
        })
        result = check_coverage(tmp_path)
        assert "src/schemas/dashboard.json" in result["uncovered"]["pages"]

    def test_page_covered_when_blueprint_mentions_it(self, tmp_path):
        _write(tmp_path, "src/schemas/dashboard.json", {"title": "Dashboard"})
        _write(tmp_path, "contracts/nav-flow.json", {
            "pages": [{"id": "dash", "route": "/dashboard",
                       "schemaFile": "src/schemas/dashboard.json"}],
        })
        # Build the blueprint — it will render the page via nav-flow.
        write_blueprint(tmp_path)
        result = check_coverage(tmp_path)
        # Now the page is referenced in the doc.
        assert "src/schemas/dashboard.json" not in result["uncovered"]["pages"]


class TestTableCoverage:
    def test_table_name_variants(self):
        assert "Tenant" in _table_name_variants("tenants")
        assert "MaintenanceRequest" in _table_name_variants("maintenance_requests")
        # Snake singular preserved for direct-match.
        assert "tenant" in _table_name_variants("tenants")

    def test_singularize(self):
        assert _snake_singularize("tenants") == "tenant"
        assert _snake_singularize("companies") == "company"
        assert _snake_singularize("boxes") == "box"

    def test_snake_to_camel(self):
        assert _snake_to_camel("maintenance_requests") == "MaintenanceRequests"
        assert _snake_to_camel("user") == "User"

    def test_table_flagged_when_missing_from_blueprint(self, tmp_path):
        _write(tmp_path, "src/db/schema/orphan.ts",
               'import { pgTable } from "drizzle-orm/pg-core";\n'
               'export const orphan = pgTable("orphan_table", {});\n')
        result = check_coverage(tmp_path)
        assert "orphan_table" in result["uncovered"]["tables"]

    def test_forge_internal_tables_excluded(self, tmp_path):
        _write(tmp_path, "src/db/schema/_forge_files.ts",
               'import { pgTable } from "drizzle-orm/pg-core";\n'
               'export const files = pgTable("forge_files", {});\n')
        result = check_coverage(tmp_path)
        # Not in uncovered — filtered out entirely.
        assert "forge_files" not in result["uncovered"]["tables"]
        assert "files" not in result["uncovered"]["tables"]

    def test_table_covered_when_entity_camelcase_in_blueprint(self, tmp_path):
        _write(tmp_path, "src/db/schema/tenants.ts",
               'import { pgTable } from "drizzle-orm/pg-core";\n'
               'export const tenants = pgTable("tenants", {});\n')
        _write(tmp_path, "contracts/plan.json", {
            "name": "PMApp",
            "entities": {"Tenant": {"fields": [{"name": "id", "type": "uuid"}]}},
        })
        write_blueprint(tmp_path)
        result = check_coverage(tmp_path)
        # Tenant entity in blueprint → tenants table considered covered
        # via CamelCase-singular match.
        assert "tenants" not in result["uncovered"]["tables"]


class TestWorkflowCoverage:
    def test_workflow_file_flagged(self, tmp_path):
        _write(tmp_path, "workflows/OrphanFlow.json",
               {"name": "OrphanFlow", "definition": {"nodes": []}})
        result = check_coverage(tmp_path)
        assert "OrphanFlow" in result["uncovered"]["workflows"]

    def test_plan_workflow_flagged_even_without_file(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {
            "name": "App",
            "workflows": [{"name": "PromisedButAbsent"}],
        })
        result = check_coverage(tmp_path)
        assert "PromisedButAbsent" in result["uncovered"]["workflows"]

    def test_workflow_covered_when_in_blueprint(self, tmp_path):
        _write(tmp_path, "workflows/ProcessOrder.json", {
            "name": "ProcessOrder",
            "definition": {"nodes": [{"id": "trigger", "type": "trigger"}]},
        })
        write_blueprint(tmp_path)
        result = check_coverage(tmp_path)
        assert "ProcessOrder" not in result["uncovered"]["workflows"]


class TestEntityCoverage:
    def test_entity_covered_when_in_blueprint(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {
            "name": "MyApp",
            "entities": {"Tenant": {"fields": [{"name": "id"}]}},
        })
        write_blueprint(tmp_path)
        result = check_coverage(tmp_path)
        assert "Tenant" not in result["uncovered"]["entities"]


class TestRouteCoverage:
    def test_navflow_route_covered_when_rendered(self, tmp_path):
        _write(tmp_path, "contracts/nav-flow.json", {
            "pages": [{"id": "p1", "route": "/settings", "title": "Settings"}],
            "transitions": [],
        })
        write_blueprint(tmp_path)
        result = check_coverage(tmp_path)
        assert "/settings" not in result["uncovered"]["routes"]


class TestUncoveredSectionSelfExclusion:
    def test_uncovered_section_ignored_when_scanning(self, tmp_path):
        # Simulate a blueprint that lists 'orphan.json' inside its own
        # Uncovered section — a naive scan would call it "covered".
        (tmp_path / "BLUEPRINT.md").write_text(
            "# App\n\n"
            "## Data Model\n\n(nothing)\n\n"
            "## Uncovered Artifacts\n\n"
            "### Pages (1)\n- `src/schemas/orphan.json`\n\n"
            "## Something Else\n\nfoo\n",
            encoding="utf-8",
        )
        _write(tmp_path, "src/schemas/orphan.json", {"title": "Orphan"})
        result = check_coverage(tmp_path)
        # The self-reference in the Uncovered section must NOT count.
        assert "src/schemas/orphan.json" in result["uncovered"]["pages"]

    def test_strip_uncovered_helper(self):
        text = (
            "## Data Model\n\nfoo\n\n"
            "## Uncovered Artifacts\n\nbar\n- item\n\n"
            "## Design\n\nbaz\n"
        )
        out = _strip_uncovered_section(text)
        assert "Uncovered" not in out
        assert "## Data Model" in out
        assert "## Design" in out


class TestUncoveredSectionInBlueprint:
    def test_orphan_table_appears_in_uncovered(self, tmp_path):
        # A pgTable declaration with no matching entity is a canonical
        # orphan — the builder's Data Model section only knows about
        # plan/registry entities, so this table has no other section.
        _write(tmp_path, "src/db/schema/mystery.ts",
               'import { pgTable } from "drizzle-orm/pg-core";\n'
               'export const mystery = pgTable("mystery_table", {});\n')
        md = build_blueprint(tmp_path)
        assert "## Uncovered Artifacts" in md
        assert "mystery_table" in md

    def test_no_section_when_fully_covered(self, tmp_path):
        # Nothing on disk → nothing to cover → no uncovered section.
        md = build_blueprint(tmp_path)
        assert "## Uncovered Artifacts" not in md

    def test_no_section_when_page_natively_rendered(self, tmp_path):
        # A schema file the builder emits as a page is NOT uncovered —
        # it's referenced by the Pages section it just rendered.
        _write(tmp_path, "src/schemas/dashboard.json", {"title": "Dashboard"})
        md = build_blueprint(tmp_path)
        assert "## Uncovered Artifacts" not in md, md


class TestCoveragePercent:
    def test_pct_reflects_ratio(self, tmp_path):
        # 2 pages, 1 uncovered → 50%
        _write(tmp_path, "src/schemas/one.json", {"title": "One"})
        _write(tmp_path, "src/schemas/two.json", {"title": "Two"})
        (tmp_path / "BLUEPRINT.md").write_text(
            "# App\n\nsee src/schemas/one.json\n", encoding="utf-8",
        )
        result = check_coverage(tmp_path)
        assert result["covered"] == 1
        assert result["coverage_pct"] == 50.0


class TestFromSourcesEntry:
    def test_from_sources_agrees_with_check_coverage(self, tmp_path):
        _write(tmp_path, "src/schemas/orphan.json", {"title": "Orphan"})
        _write(tmp_path, "contracts/plan.json",
               {"name": "App", "entities": {"Tenant": {}}})
        a = check_coverage(tmp_path)
        srcs = _load_sources(tmp_path)
        b = check_coverage_from_sources(tmp_path, srcs)
        assert a == b
