"""End-to-end unit coverage for the ocr_document workflow action across the
backend surfaces it touches: config-spec registration, translator legality,
config normalisation, and planner keyword classifier.

Runtime handler (backend/templates/runtime/workflows/ocr.ts) is a TypeScript
template file — a separate vitest suite in packages/renderer/tests will cover
it once the handler is wired into the shared runtime harness.
"""
from __future__ import annotations

import pytest


# ────────────────────────────────────────────────────────────
# Config spec
# ────────────────────────────────────────────────────────────

class TestNodeConfigSpecs:
    def test_ocr_document_registered(self):
        from services.node_config_specs import NODE_CONFIG_SPECS
        assert "ocr_document" in NODE_CONFIG_SPECS

    def test_ocr_document_has_url_required(self):
        from services.node_config_specs import NODE_CONFIG_SPECS
        keys = {e.key: e for e in NODE_CONFIG_SPECS["ocr_document"]}
        assert "PADDLEOCR_URL" in keys
        assert keys["PADDLEOCR_URL"].required is True
        assert keys["PADDLEOCR_URL"].kind == "url"
        assert keys["PADDLEOCR_URL"].provider == "paddleocr"

    def test_ocr_document_api_key_optional(self):
        from services.node_config_specs import NODE_CONFIG_SPECS
        keys = {e.key: e for e in NODE_CONFIG_SPECS["ocr_document"]}
        assert "PADDLEOCR_API_KEY" in keys
        assert keys["PADDLEOCR_API_KEY"].required is False
        assert keys["PADDLEOCR_API_KEY"].kind == "password"
        assert keys["PADDLEOCR_API_KEY"].provider == "paddleocr"


# ────────────────────────────────────────────────────────────
# Workflow translator legality
# ────────────────────────────────────────────────────────────

class TestTranslatorLegality:
    def test_ocr_document_in_actiontypes(self):
        from services.workflow_step_translator import _ACTIONTYPES
        assert "ocr_document" in _ACTIONTYPES

    def test_bare_ocr_document_step_resolves_to_action(self):
        from services.workflow_step_translator import _resolve_node_type
        node_type, forced_at = _resolve_node_type({"type": "ocr_document"})
        assert node_type == "action"
        assert forced_at == "ocr_document"

    def test_config_actionType_ocr_document_resolves(self):
        from services.workflow_step_translator import _resolve_node_type
        node_type, forced_at = _resolve_node_type(
            {"type": "action", "config": {"actionType": "ocr_document"}}
        )
        assert node_type == "action"
        # `type: "action"` already, so translator does not force actionType a
        # second time — the caller's config keeps ocr_document.
        assert forced_at is None or forced_at == "ocr_document"


# ────────────────────────────────────────────────────────────
# Config normalisation
# ────────────────────────────────────────────────────────────

class TestConfigNormalisation:
    def _translate(self, cfg: dict, label: str = "OCR Document"):
        from services.workflow_step_translator import _translate_config
        return _translate_config(cfg, label)

    def test_file_alias_becomes_ocrFileRef(self):
        out = self._translate({"actionType": "ocr_document", "file": "{{doc.id}}"})
        assert out["ocrFileRef"] == "{{doc.id}}"

    def test_fileRef_alias_becomes_ocrFileRef(self):
        out = self._translate({"actionType": "ocr_document", "fileRef": "{{input}}"})
        assert out["ocrFileRef"] == "{{input}}"

    def test_document_alias_becomes_ocrFileRef(self):
        out = self._translate(
            {"actionType": "ocr_document", "document": "{{trigger.file}}"}
        )
        assert out["ocrFileRef"] == "{{trigger.file}}"

    def test_missing_file_defaults_to_input_binding(self):
        out = self._translate({"actionType": "ocr_document"})
        assert out["ocrFileRef"] == "{{input}}"

    def test_scalar_page_wraps_into_list(self):
        out = self._translate({"actionType": "ocr_document", "pages": 3})
        assert out["ocrPages"] == [3]

    def test_list_pages_preserved(self):
        out = self._translate(
            {"actionType": "ocr_document", "pages": [1, 2, 5]}
        )
        assert out["ocrPages"] == [1, 2, 5]

    def test_language_alias_becomes_ocrLanguage(self):
        out = self._translate(
            {"actionType": "ocr_document", "language": "zh"}
        )
        assert out["ocrLanguage"] == "zh"

    def test_lang_alias_becomes_ocrLanguage(self):
        out = self._translate({"actionType": "ocr_document", "lang": "ar"})
        assert out["ocrLanguage"] == "ar"

    def test_canonical_ocrFileRef_wins_over_alias(self):
        out = self._translate(
            {
                "actionType": "ocr_document",
                "ocrFileRef": "{{a}}",
                "file": "{{b}}",
                "fileRef": "{{c}}",
            }
        )
        assert out["ocrFileRef"] == "{{a}}"


# ────────────────────────────────────────────────────────────
# Planner classifier
# ────────────────────────────────────────────────────────────

class TestPlannerClassifier:
    @pytest.mark.parametrize("label", [
        "OCR document",
        "OCR file",
        "OCR pdf",
        "Run OCR",
        "Scan document",
        "Scan pdf",
        "Digitize records",
        "Extract text from document",
        "Extract text from pdf",
        "Extract text from scan",
    ])
    def test_ocr_keywords_map_to_ocr_document(self, label):
        from services.workflow_generator import _classify_step
        assert _classify_step(label) == "ocr_document"

    def test_extract_without_ocr_still_maps_to_ai_extract(self):
        """`extract fields from a CV` is an LLM job, not an OCR job — the
        classifier must not steal every `extract` label."""
        from services.workflow_generator import _classify_step
        assert _classify_step("Extract candidate fields") == "ai_extract"

    def test_extract_text_from_email_stays_ai_extract(self):
        """Only the document/pdf/scan variants of `extract text from …`
        bind to OCR; plain text sources belong to the LLM extractor."""
        from services.workflow_generator import _classify_step
        assert _classify_step("Extract text from email") == "ai_extract"
