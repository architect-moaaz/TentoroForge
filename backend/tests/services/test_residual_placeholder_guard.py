"""A `{{token}}` surviving into JSX is a build-breaking bug, not a cosmetic one.

Live failure on Vercel:

    Error occurred prerendering page "/_not-found"
    ReferenceError: app_name is not defined
        at stringify (<anonymous>)

`{{app_name}}` in JSX text position is the object literal `{app_name}` —
shorthand for `{app_name: app_name}` — so it compiles, typechecks, passes
every existing gate, and dies at prerender. `/_not-found` renders the root
layout, so it is the first page to hit it and the export aborts there.

The hard part is not detection, it is NOT firing on legitimate JSX. Two
real shapes from the corpus must stay silent:

* ``style={{ height }}``      — shorthand property, so a colon test fails
* ``"{{items}}"`` in a string — the workflow runtime carries binding syntax
  in string literals across ~417 `.ts` files by design
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.residual_placeholder_guard import (apply_residual_placeholder_guard,
                                                 scan_app, scan_text)


class TestDangerousForms:
    def test_jsx_text_position_is_caught(self):
        """The exact line that broke the Vercel build."""
        hits = scan_text("      Return to {{app_name}}\n")
        assert [h["token"] for h in hits] == ["app_name"]
        assert hits[0]["line"] == 1

    @pytest.mark.parametrize("tok", ["app_name", "home_route", "app_initial"])
    def test_every_edge_template_token(self, tok):
        assert scan_text(f"<p>Go to {{{{{tok}}}}}</p>")

    def test_multiple_on_one_line_both_reported(self):
        hits = scan_text("{{app_name}} and {{home_route}}")
        assert {h["token"] for h in hits} == {"app_name", "home_route"}

    def test_line_number_and_snippet_are_actionable(self):
        hits = scan_text("line one\nline two\n  Return to {{app_name}}\n")
        assert hits[0]["line"] == 3
        assert "Return to" in hits[0]["snippet"]


class TestLegitimateJsxStaysSilent:
    """Every one of these is real, valid JSX taken from the output corpus."""

    def test_style_object_with_shorthand_property(self):
        # The false positive that killed the naive colon-based rule.
        assert scan_text('<div style={{ height }}>') == []

    def test_style_object_with_explicit_key(self):
        assert scan_text("<div style={{ color: 'red' }}>") == []

    @pytest.mark.parametrize("attr", ["style", "sx", "config", "data"])
    def test_any_attribute_position_is_legal(self, attr):
        assert scan_text(f"<X {attr}={{{{ value }}}} />") == []

    def test_binding_syntax_inside_a_string_literal(self):
        # How the workflow runtime legitimately carries bindings.
        assert scan_text('const b = "{{items}}";') == []
        assert scan_text("const b = '{{items}}';") == []
        assert scan_text("const b = `{{items}}`;") == []

    def test_binding_syntax_inside_a_comment(self):
        assert scan_text("// resolves {{items}} at runtime") == []

    def test_empty_and_plain_source(self):
        assert scan_text("") == []
        assert scan_text("export const x = 1;\n") == []


class TestScanApp:
    def _app(self, tmp_path: Path, rel: str, body: str) -> Path:
        p = tmp_path / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    def test_finds_hit_and_records_relative_path(self, tmp_path):
        self._app(tmp_path, "app/not-found.tsx", "  Return to {{app_name}}\n")
        res = scan_app(tmp_path)
        assert res["files"] == 1
        assert res["findings"][0]["file"] == "src/app/not-found.tsx"

    def test_ts_files_are_not_scanned(self, tmp_path):
        """`.ts` has no JSX — it cannot fail this way, and the runtime is
        full of legitimate `{{binding}}` strings."""
        self._app(tmp_path, "runtime/ai.ts", 'const t = "{{prompt}}";\nlet x = {{prompt}};\n')
        assert scan_app(tmp_path)["findings"] == []

    def test_missing_src_is_not_a_crash(self, tmp_path):
        assert scan_app(tmp_path) == {"findings": [], "files": 0, "scanned": 0}

    def test_clean_app_reports_zero_but_counts_scanned(self, tmp_path):
        self._app(tmp_path, "app/page.tsx", "<div style={{ height }}>ok</div>")
        res = scan_app(tmp_path)
        assert res["findings"] == [] and res["scanned"] == 1


class TestReportArtifact:
    def test_report_written_even_when_clean(self, tmp_path):
        """A missing report must mean 'did not run', never 'found nothing'."""
        (tmp_path / "src").mkdir(parents=True)
        apply_residual_placeholder_guard(tmp_path)
        rep = tmp_path / "contracts" / "placeholder-report.json"
        assert rep.is_file()
        assert json.loads(rep.read_text())["findings"] == []

    def test_report_carries_the_findings(self, tmp_path):
        d = tmp_path / "src" / "app"
        d.mkdir(parents=True)
        (d / "not-found.tsx").write_text("Return to {{app_name}}", encoding="utf-8")
        apply_residual_placeholder_guard(tmp_path)
        data = json.loads(
            (tmp_path / "contracts" / "placeholder-report.json").read_text())
        assert data["findings"][0]["token"] == "app_name"
