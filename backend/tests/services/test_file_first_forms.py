"""Tests for services.file_first_forms — file-first workflow upload forms.

The doc-intel reference contract: an upload form supplies the FILE; the
system derives everything else. The generated form instead asks the user
to TYPE originalFilename / fileMimeType / uploadedById / id — and the
visible originalFilename Input collides with FileUpload's hidden
companion input of the same name, so the empty visible value wins and
the workflow rejects the insert (the atb0m97x upload class).
"""
from __future__ import annotations

import json
from pathlib import Path

from services.file_first_forms import apply_file_first_forms


def _mk_app(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "workflows").mkdir(parents=True)

    page = {
        "id": "upload", "route": "/upload",
        "root": {"type": "Stack", "children": [
            {"type": "Form", "id": "f1",
             "props": {"workflow": "ProcessDocumentWorkflow"},
             "children": [
                 {"type": "Input", "id": "c1",
                  "props": {"name": "originalFilename",
                            "label": "Original Filename"}},
                 {"type": "FileUpload", "id": "c2",
                  "props": {"name": "filePath", "label": "File"}},
                 {"type": "Input", "id": "c3",
                  "props": {"name": "fileMimeType",
                            "label": "File Mime Type"}},
                 {"type": "Select", "id": "c4",
                  "props": {"name": "status", "label": "Status",
                            "options": [{"label": "Queued",
                                         "value": "queued"}]}},
                 {"type": "Input", "id": "c5",
                  "props": {"name": "uploadedById",
                            "label": "Uploaded By Id"}},
                 {"type": "Input", "id": "c6",
                  "props": {"name": "id", "label": "Id"}},
                 {"type": "Input", "id": "c7",
                  "props": {"name": "title", "label": "Title"}},
                 {"type": "Button", "id": "c8",
                  "props": {"submit": True, "label": "Upload"}},
             ]},
        ]},
    }
    (root / "src" / "schemas" / "upload.json").write_text(json.dumps(page))

    wf = {
        "name": "ProcessDocumentWorkflow",
        "definition": {"nodes": [
            {"id": "trigger", "type": "trigger",
             "data": {"nodeType": "trigger", "config": {}}},
            {"id": "insert_document", "type": "action",
             "data": {"nodeType": "action",
                      "config": {"actionType": "db_insert",
                                 "table": "documents",
                                 "values": {
                                     "originalFilename":
                                         "{{originalFilename}}",
                                     "filePath": "{{filePath}}",
                                     "fileMimeType": "{{fileMimeType}}",
                                     "uploadedById": "{{uploadedById}}",
                                     "title": "{{title}}",
                                     "status": "queued",
                                     "uploadedAt": "{{now}}",
                                 }}}},
        ], "edges": []},
    }
    (root / "workflows" / "ProcessDocumentWorkflow.json").write_text(
        json.dumps(wf))
    return root


def _form_children(root: Path) -> list[dict]:
    doc = json.loads(
        (root / "src" / "schemas" / "upload.json").read_text())
    return doc["root"]["children"][0]["children"]


def _names(root: Path) -> list[str]:
    return [(c.get("props") or {}).get("name") for c in _form_children(root)]


def _insert_values(root: Path) -> dict:
    wf = json.loads(
        (root / "workflows" / "ProcessDocumentWorkflow.json").read_text())
    for n in wf["definition"]["nodes"]:
        cfg = (n.get("data") or {}).get("config") or {}
        if cfg.get("actionType") == "db_insert":
            return cfg["values"]
    raise AssertionError("no db_insert node")


def test_derived_metadata_inputs_removed(tmp_path):
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    names = _names(root)
    assert "originalFilename" not in names
    assert "fileMimeType" not in names


def test_fileupload_companion_fields_wired(tmp_path):
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    fu = next(c for c in _form_children(root) if c["type"] == "FileUpload")
    assert fu["props"]["filenameField"] == "originalFilename"
    assert fu["props"]["mimeTypeField"] == "fileMimeType"


def test_system_fields_removed(tmp_path):
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    names = _names(root)
    assert "id" not in names
    assert "uploadedById" not in names
    # status has a literal value in the insert — the user never picks it
    assert "status" not in names


def test_real_user_field_kept(tmp_path):
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    names = _names(root)
    assert "title" in names          # a genuine {{binding}} the user types
    assert "filePath" in names       # the FileUpload itself stays


def test_user_fk_rewritten_to_session_sentinel(tmp_path):
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    assert _insert_values(root)["uploadedById"] == "$user.id"


def test_now_binding_rewritten_to_sentinel(tmp_path):
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    assert _insert_values(root)["uploadedAt"] == "$now"


def test_metadata_bindings_survive_in_workflow(tmp_path):
    """The insert still binds the metadata — FileUpload's hidden inputs
    now supply the values under the same names."""
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    vals = _insert_values(root)
    assert vals["originalFilename"] == "{{originalFilename}}"
    assert vals["fileMimeType"] == "{{fileMimeType}}"


def test_idempotent(tmp_path):
    root = _mk_app(tmp_path)
    apply_file_first_forms(root)
    once_page = (root / "src" / "schemas" / "upload.json").read_text()
    once_wf = (root / "workflows" / "ProcessDocumentWorkflow.json").read_text()
    rep2 = apply_file_first_forms(root)
    assert (root / "src" / "schemas" / "upload.json").read_text() == once_page
    assert (root / "workflows" /
            "ProcessDocumentWorkflow.json").read_text() == once_wf
    assert rep2["summary"]["forms_rewritten"] == 0


def test_form_without_fileupload_untouched(tmp_path):
    root = _mk_app(tmp_path)
    page = json.loads(
        (root / "src" / "schemas" / "upload.json").read_text())
    kids = page["root"]["children"][0]["children"]
    page["root"]["children"][0]["children"] = [
        c for c in kids if c["type"] != "FileUpload"]
    (root / "src" / "schemas" / "upload.json").write_text(json.dumps(page))
    rep = apply_file_first_forms(root)
    assert rep["summary"]["forms_rewritten"] == 0
    assert "originalFilename" in _names(root)


def test_derived_column_fileupload_removed(tmp_path):
    """An earlier repair can mis-render fileMimeType as a SECOND
    FileUpload; the pass drops it and keeps the real file control."""
    root = _mk_app(tmp_path)
    page = json.loads(
        (root / "src" / "schemas" / "upload.json").read_text())
    page["root"]["children"][0]["children"].insert(3, {
        "type": "FileUpload", "id": "c9",
        "props": {"name": "fileMimeType", "label": "File Mime Type"}})
    (root / "src" / "schemas" / "upload.json").write_text(json.dumps(page))
    apply_file_first_forms(root)
    uploads = [c for c in _form_children(root) if c["type"] == "FileUpload"]
    assert [u["props"]["name"] for u in uploads] == ["filePath"]


def test_emptied_card_shells_removed(tmp_path):
    """Controls live inside toned section Cards; when the pass removes
    every control in a Card, the Card+Heading shell must go too — no
    decorative 'Processing'/'Record Meta' boxes left behind."""
    root = _mk_app(tmp_path)
    page = json.loads(
        (root / "src" / "schemas" / "upload.json").read_text())
    form = page["root"]["children"][0]
    kids = {(c.get("props") or {}).get("name"): c for c in form["children"]
            if isinstance(c, dict)}
    form["children"] = [
        {"type": "Card", "id": "sec1", "props": {},
         "children": [{"type": "Heading",
                       "props": {"content": "Upload", "level": 2}},
                      kids["filePath"], kids["title"]]},
        {"type": "Card", "id": "sec2", "props": {},
         "children": [{"type": "Heading",
                       "props": {"content": "Processing", "level": 2}},
                      kids["status"]]},
        {"type": "Card", "id": "sec3", "props": {},
         "children": [{"type": "Heading",
                       "props": {"content": "Record Meta", "level": 2}},
                      kids["id"]]},
    ]
    (root / "src" / "schemas" / "upload.json").write_text(json.dumps(page))
    apply_file_first_forms(root)
    doc = json.loads(
        (root / "src" / "schemas" / "upload.json").read_text())
    form = doc["root"]["children"][0]
    card_ids = [c.get("id") for c in form["children"]
                if isinstance(c, dict) and c.get("type") == "Card"]
    assert card_ids == ["sec1"]          # shells sec2/sec3 removed
    text = json.dumps(doc)
    assert "Processing" not in text and "Record Meta" not in text
    assert "Upload" in text              # real section kept


def test_missing_workflow_file_no_crash(tmp_path):
    root = _mk_app(tmp_path)
    (root / "workflows" / "ProcessDocumentWorkflow.json").unlink()
    rep = apply_file_first_forms(root)
    assert rep["summary"]["forms_rewritten"] == 0


# ─────────── workflow-produced outputs are not user inputs ───────────

def _add_output_steps_and_controls(root: Path) -> None:
    """Extend the fixture with the atb0m97x 'Extraction Results' shape:
    OCR + AI steps PRODUCE ocrResult/extractedFields/confidenceScore,
    a persist step consumes the AI output via {{bindings}}, and the form
    renders editable controls for all three."""
    wf_path = root / "workflows" / "ProcessDocumentWorkflow.json"
    wf = json.loads(wf_path.read_text())
    wf["definition"]["nodes"] += [
        {"id": "ocr_sidecar", "type": "action",
         "data": {"nodeType": "action",
                  "config": {"actionType": "http_call",
                             "outputVar": "ocrResult"}}},
        {"id": "ai_extract_fields", "type": "action",
         "data": {"nodeType": "action",
                  "config": {"actionType": "ai_extract",
                             "input": "{{ocrResult.text}}",
                             "outputVar": "aiResult",
                             "aiExtractFields": ["extractedFields",
                                                 "confidenceScore"]}}},
        {"id": "persist_results", "type": "action",
         "data": {"nodeType": "action",
                  "config": {"actionType": "db_update",
                             "table": "documents",
                             "values": {
                                 "extractedFields": "{{extractedFields}}",
                                 "confidenceScore": "{{confidenceScore}}"},
                             "where": {"id": "{{insert_document.id}}"}}}},
    ]
    wf_path.write_text(json.dumps(wf))

    page_path = root / "src" / "schemas" / "upload.json"
    page = json.loads(page_path.read_text())
    page["root"]["children"][0]["children"] += [
        {"type": "RichTextEditor", "id": "o1",
         "props": {"name": "ocrText", "label": "Ocr Text"}},
        {"type": "KeyValueInput", "id": "o2",
         "props": {"name": "extractedFields", "label": "Extracted Fields"}},
        {"type": "Slider", "id": "o3",
         "props": {"name": "confidenceScore", "label": "Confidence Score"}},
    ]
    page_path.write_text(json.dumps(page))


def test_workflow_produced_outputs_removed(tmp_path):
    """extractedFields/confidenceScore ARE {{referenced}} by the persist
    step — but an earlier step PRODUCES them, so they are not user
    inputs. ocrText is never referenced at all (dead)."""
    root = _mk_app(tmp_path)
    _add_output_steps_and_controls(root)
    apply_file_first_forms(root)
    names = _names(root)
    assert "extractedFields" not in names
    assert "confidenceScore" not in names
    assert "ocrText" not in names
    assert "title" in names              # genuine user input untouched


def test_output_card_shell_removed(tmp_path):
    """The 'Extraction Results' card that held only produced-output
    controls collapses once they're pruned."""
    root = _mk_app(tmp_path)
    _add_output_steps_and_controls(root)
    page_path = root / "src" / "schemas" / "upload.json"
    page = json.loads(page_path.read_text())
    form = page["root"]["children"][0]
    outputs = [c for c in form["children"]
               if c.get("id") in ("o1", "o2", "o3")]
    form["children"] = [c for c in form["children"] if c not in outputs]
    form["children"].append(
        {"type": "Card", "id": "results", "props": {},
         "children": [
             {"type": "Heading", "props": {"content": "Extraction Results",
                                           "level": 2}},
             {"type": "Text", "props": {"content":
                                        "Populated after OCR completes"}},
         ] + outputs})
    page_path.write_text(json.dumps(page))
    apply_file_first_forms(root)
    text = (root / "src" / "schemas" / "upload.json").read_text()
    assert "Extraction Results" not in text


# ─────────────────── upload label + submit coherence ───────────────────

def test_column_named_upload_label_humanized(tmp_path):
    """'File Path' (the storage column, mechanically humanized) is not
    an upload label — replace with 'Upload document'."""
    root = _mk_app(tmp_path)
    page_path = root / "src" / "schemas" / "upload.json"
    page = json.loads(page_path.read_text())
    fu = next(c for c in page["root"]["children"][0]["children"]
              if c["type"] == "FileUpload")
    fu["props"]["label"] = "File Path"
    page_path.write_text(json.dumps(page))
    apply_file_first_forms(root)
    fu = next(c for c in _form_children(root) if c["type"] == "FileUpload")
    assert fu["props"]["label"] == "Upload document"


def test_meaningful_upload_label_kept(tmp_path):
    root = _mk_app(tmp_path)
    page_path = root / "src" / "schemas" / "upload.json"
    page = json.loads(page_path.read_text())
    fu = next(c for c in page["root"]["children"][0]["children"]
              if c["type"] == "FileUpload")
    fu["props"]["label"] = "Invoice PDF"
    page_path.write_text(json.dumps(page))
    apply_file_first_forms(root)
    fu = next(c for c in _form_children(root) if c["type"] == "FileUpload")
    assert fu["props"]["label"] == "Invoice PDF"


def test_workflow_form_submit_coherence(tmp_path):
    """A workflow-trigger form must not keep the CRUD scaffold's data
    onSubmit or its generic 'Save' label."""
    root = _mk_app(tmp_path)
    page_path = root / "src" / "schemas" / "upload.json"
    page = json.loads(page_path.read_text())
    form = page["root"]["children"][0]
    form["props"]["onSubmit"] = {"kind": "data", "op": "insert",
                                 "entity": "Document",
                                 "navigate": "/document"}
    form["props"]["submitLabel"] = "Save"
    page_path.write_text(json.dumps(page))
    apply_file_first_forms(root)
    doc = json.loads((root / "src" / "schemas" / "upload.json").read_text())
    props = doc["root"]["children"][0]["props"]
    assert "onSubmit" not in props
    assert props["submitLabel"] == "Process Document"


def test_custom_submit_label_kept(tmp_path):
    root = _mk_app(tmp_path)
    page_path = root / "src" / "schemas" / "upload.json"
    page = json.loads(page_path.read_text())
    page["root"]["children"][0]["props"]["submitLabel"] = "Upload & Extract"
    page_path.write_text(json.dumps(page))
    apply_file_first_forms(root)
    doc = json.loads((root / "src" / "schemas" / "upload.json").read_text())
    assert doc["root"]["children"][0]["props"]["submitLabel"] == \
        "Upload & Extract"
