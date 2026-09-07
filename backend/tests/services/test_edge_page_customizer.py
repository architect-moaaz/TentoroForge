"""Tests for services.edge_page_customizer — Spec C5.

Verifies {{app_name}} / {{app_initial}} / {{home_route}} substitution
across all 5 edge templates + the shared EdgePageFrame component.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.edge_page_customizer import (
    customize_edge_pages,
    is_enabled,
)


def _seed_templates(root: Path) -> None:
    """Simulate what runtime_injector copies into a generated app."""
    app_dir = root / "src" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "not-found.tsx").write_text(
        'import Link from "next/link";\n'
        'export default function NF() {\n'
        '  return <>\n'
        '    <h1>We can\'t find that page</h1>\n'
        '    <Link href="{{home_route}}">Return to {{app_name}}</Link>\n'
        '  </>;\n'
        '}\n', encoding="utf-8")
    (app_dir / "error.tsx").write_text(
        '"use client";\nimport Link from "next/link";\n'
        'export default function E() {\n'
        '  return <p>Back to <Link href="{{home_route}}">{{app_name}}</Link></p>;\n'
        '}\n', encoding="utf-8")
    (app_dir / "forbidden.tsx").write_text(
        'export default function F() { return <>Return to {{app_name}}</>; }\n',
        encoding="utf-8")
    (app_dir / "loading.tsx").write_text(
        'export default function L() { return <>Loading…</>; }\n',
        encoding="utf-8")
    (app_dir / "maintenance.tsx").write_text(
        'export default function M() { return <>{{app_name}} is offline</>; }\n',
        encoding="utf-8")
    comp = root / "src" / "components"
    comp.mkdir(parents=True)
    (comp / "EdgePageFrame.tsx").write_text(
        'const APP_INITIAL = "{{app_initial}}";\n'
        'const APP_NAME_LABEL = "{{app_name}}";\n'
        'export function EdgePageFrame() { return <div>{APP_INITIAL}</div>; }\n',
        encoding="utf-8")


# ────────────────────────────────────────────────────────────
# Feature flag
# ────────────────────────────────────────────────────────────

class TestFlag:
    def test_default_enabled(self, monkeypatch):
        # Default ON: unsubstituted {{app_name}} placeholders are invalid
        # JSX and fail `next build` on /_not-found — substitution is a
        # correctness requirement, so the flag is opt-OUT only.
        monkeypatch.delenv("FORGE_POLISH_EDGE_PAGES", raising=False)
        assert is_enabled() is True

    def test_disabled_when_zero(self, monkeypatch):
        monkeypatch.setenv("FORGE_POLISH_EDGE_PAGES", "0")
        assert is_enabled() is False

    def test_enabled_when_truthy(self, monkeypatch):
        for v in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("FORGE_POLISH_EDGE_PAGES", v)
            assert is_enabled() is True


# ────────────────────────────────────────────────────────────
# Substitution
# ────────────────────────────────────────────────────────────

class TestSubstitution:
    def test_substitutes_across_all_edge_files(self, tmp_path):
        _seed_templates(tmp_path)
        (tmp_path / "package.json").write_text(json.dumps({"name": "leaseflow"}), encoding="utf-8")
        res = customize_edge_pages(str(tmp_path))
        # loading.tsx has no tokens in this fixture (matches real
        # template: loading is copy-free); the other 4 tsx + 1 component
        # do → 5 files rewritten.
        assert res["files"] == 5
        assert res["tokens_replaced"] > 0
        for rel in ("src/app/not-found.tsx", "src/app/error.tsx",
                    "src/app/forbidden.tsx", "src/app/maintenance.tsx",
                    "src/components/EdgePageFrame.tsx"):
            text = (tmp_path / rel).read_text(encoding="utf-8")
            assert "{{app_name}}" not in text, f"leftover in {rel}"

    def test_home_route_from_nav_flow(self, tmp_path):
        _seed_templates(tmp_path)
        contracts = tmp_path / "src" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "nav-flow.json").write_text(json.dumps({
            "home": "/dashboard",
        }), encoding="utf-8")
        (tmp_path / "package.json").write_text(json.dumps({"name": "leaseflow"}), encoding="utf-8")
        customize_edge_pages(str(tmp_path))
        nf = (tmp_path / "src/app/not-found.tsx").read_text(encoding="utf-8")
        assert 'href="/dashboard"' in nf
        assert "Return to Leaseflow" in nf

    def test_home_route_from_nav_flow_entries_list(self, tmp_path):
        _seed_templates(tmp_path)
        contracts = tmp_path / "src" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "nav-flow.json").write_text(json.dumps({
            "entries": [{"route": "/leases", "label": "Leases"}],
        }), encoding="utf-8")
        customize_edge_pages(str(tmp_path), app_name="Rentr")
        nf = (tmp_path / "src/app/not-found.tsx").read_text(encoding="utf-8")
        assert 'href="/leases"' in nf

    def test_home_route_falls_back_to_slash(self, tmp_path):
        _seed_templates(tmp_path)
        customize_edge_pages(str(tmp_path), app_name="Rentr")
        nf = (tmp_path / "src/app/not-found.tsx").read_text(encoding="utf-8")
        assert 'href="/"' in nf

    def test_app_name_from_explicit_override(self, tmp_path):
        _seed_templates(tmp_path)
        customize_edge_pages(str(tmp_path), app_name="Property Manager Pro")
        m = (tmp_path / "src/app/maintenance.tsx").read_text(encoding="utf-8")
        assert "Property Manager Pro is offline" in m

    def test_app_name_from_plan_json(self, tmp_path):
        _seed_templates(tmp_path)
        contracts = tmp_path / "src" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "plan.json").write_text(json.dumps({"app_name": "HireOps"}), encoding="utf-8")
        customize_edge_pages(str(tmp_path))
        assert "HireOps" in (tmp_path / "src/app/maintenance.tsx").read_text(encoding="utf-8")

    def test_app_name_from_package_json_kebab(self, tmp_path):
        _seed_templates(tmp_path)
        (tmp_path / "package.json").write_text(json.dumps({"name": "hospital-scheduler"}), encoding="utf-8")
        customize_edge_pages(str(tmp_path))
        assert "Hospital Scheduler" in (tmp_path / "src/app/maintenance.tsx").read_text(encoding="utf-8")

    def test_app_name_from_dir_when_no_metadata(self, tmp_path):
        _seed_templates(tmp_path)
        # No plan.json, no package.json — falls back to dir basename.
        customize_edge_pages(str(tmp_path))
        # tmp_path basename is randomized; just check SOME name substituted.
        text = (tmp_path / "src/app/maintenance.tsx").read_text(encoding="utf-8")
        assert "{{app_name}}" not in text
        assert "is offline" in text

    def test_app_initial_derived_from_first_alnum(self, tmp_path):
        _seed_templates(tmp_path)
        customize_edge_pages(str(tmp_path), app_name="  9Property Manager")
        frame = (tmp_path / "src/components/EdgePageFrame.tsx").read_text(encoding="utf-8")
        assert 'APP_INITIAL = "9"' in frame

    def test_app_initial_falls_back_to_bullet_for_symbols_only(self, tmp_path):
        _seed_templates(tmp_path)
        customize_edge_pages(str(tmp_path), app_name="---")
        frame = (tmp_path / "src/components/EdgePageFrame.tsx").read_text(encoding="utf-8")
        assert 'APP_INITIAL = "•"' in frame


# ────────────────────────────────────────────────────────────
# Return contract
# ────────────────────────────────────────────────────────────

class TestReturnContract:
    def test_missing_dir_safe_no_files(self, tmp_path):
        # Points at a nonexistent path.
        res = customize_edge_pages(str(tmp_path / "nowhere"))
        assert res == {"files": 0, "tokens_replaced": 0}

    def test_no_op_when_pages_absent(self, tmp_path):
        # Directory exists, no edge files present.
        res = customize_edge_pages(str(tmp_path))
        assert res["files"] == 0

    def test_reports_resolved_name_and_route(self, tmp_path):
        _seed_templates(tmp_path)
        res = customize_edge_pages(str(tmp_path), app_name="Rentr", home_route="/home")
        assert res["app_name"] == "Rentr"
        assert res["home_route"] == "/home"


# ────────────────────────────────────────────────────────────
# Idempotency
# ────────────────────────────────────────────────────────────

class TestIdempotent:
    def test_second_run_is_a_no_op(self, tmp_path):
        _seed_templates(tmp_path)
        first = customize_edge_pages(str(tmp_path), app_name="Rentr")
        assert first["files"] == 5
        second = customize_edge_pages(str(tmp_path), app_name="Rentr")
        # No more {{tokens}} to find → no files rewritten.
        assert second["files"] == 0
        assert second["tokens_replaced"] == 0


def test_a_route_pattern_is_not_a_link_target():
    """`/survey/[slug]` is a template. Next's app router throws on it as a
    Link href — "Dynamic href found in <Link> while using the /app router" —
    and it reached a generated error page because it was simply the first
    route in nav-flow."""
    from services.edge_page_customizer import _is_linkable

    assert not _is_linkable("/survey/[slug]")
    assert not _is_linkable("/responses/[id]")
    assert _is_linkable("/surveys")
    assert _is_linkable("/")
    assert not _is_linkable("surveys")   # not absolute
    assert not _is_linkable(None)


def test_the_home_route_skips_patterns_and_takes_the_first_real_one(tmp_path):
    import json
    from services.edge_page_customizer import _derive_home_route

    nav = tmp_path / "src" / "contracts"
    nav.mkdir(parents=True)
    (nav / "nav-flow.json").write_text(json.dumps({
        "pages": [{"route": "/survey/[slug]"}, {"route": "/responses/[id]"},
                  {"route": "/surveys"}],
    }), encoding="utf-8")
    assert _derive_home_route(tmp_path) == "/surveys"


def test_an_app_of_only_detail_routes_falls_back_to_root(tmp_path):
    """Better a link to / than a link that throws."""
    import json
    from services.edge_page_customizer import _derive_home_route

    nav = tmp_path / "src" / "contracts"
    nav.mkdir(parents=True)
    (nav / "nav-flow.json").write_text(json.dumps({
        "pages": [{"route": "/survey/[slug]"}],
    }), encoding="utf-8")
    assert _derive_home_route(tmp_path) == "/"
