"""File-first workflow upload forms — the doc-intel reference contract.

The reference app's upload form (reference-apps/document-vault-*) supplies
only the FILE; everything else is derived: FileUpload's hidden companion
inputs carry the original filename + mime type, the uploader FK comes
from the session (``$user.id``), timestamps from ``$now``, and workflow
literals (``status: "queued"``) need no user input.

The generated form instead asks the user to TYPE those columns — and the
visible ``originalFilename`` Input collides with FileUpload's hidden
companion input of the same name, so the empty visible value shadows the
real one in FormData and the workflow rejects every upload (atb0m97x).

This pass makes every workflow-bound form that contains a FileUpload
file-first, deterministically:

1. Wire FileUpload's companion-input names to the REAL columns the
   workflow insert binds (``filenameField`` / ``mimeTypeField``) — the
   entity may spell them ``fileMimeType`` rather than ``mimeType``.
2. Remove visible controls for the derived metadata (the FileUpload's
   hidden inputs now supply them under the same names).
3. Remove system fields the user should never type: ``id``, lifecycle
   ``*At`` columns, user-FK columns, and any control whose name is never
   referenced as a ``{{binding}}`` anywhere in the workflow (dead input:
   a status Select when the insert uses a literal).
4. Remove controls for workflow-PRODUCED variables: a ``{{binding}}``
   satisfied by an earlier step's output (``outputVar`` /
   ``aiExtractFields``) is not a user input, even though it is
   referenced — the atb0m97x 'Extraction Results' card asked the user
   to type OCR text and drag a confidence slider the AI step produces.
5. Rewrite workflow values for removed user-FKs to ``$user.id`` and the
   unresolvable ``{{now}}`` / ``{{today}}`` bindings to the engine's
   ``$now`` / ``$today`` sentinels.
6. Presentation coherence: relabel the drop zone when its label is just
   the storage column ("File Path" → "Upload document"), strip the CRUD
   scaffold's contradictory data ``onSubmit`` from a workflow form, and
   replace a generic ``Save``/``Submit`` submitLabel with the humanized
   workflow action ("Process Document").

Genuine user inputs (any other ``{{binding}}``-referenced control) stay.
Idempotent; missing files never raise.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FILENAME_COLS = {"originalfilename", "filename", "originalname"}
_MIME_COLS = {"mimetype", "filemimetype", "contenttype"}
_SIZE_COLS = {"filesize", "sizebytes"}
_USER_FK_RE = re.compile(
    r"(uploadedby|createdby|submittedby|ownerid|owner_id|authorid)(id)?$",
    re.IGNORECASE)
_LIFECYCLE_RE = re.compile(r".+(At|_at)$")
_BINDING_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")

_CONTROL_TYPES = {"Input", "Select", "Textarea", "NumberInput",
                  "DatePicker", "TimePicker", "Switch", "Checkbox",
                  "RichTextEditor", "KeyValueInput", "Slider", "Combobox",
                  "RadioGroup", "EmailInput", "PhoneInput", "UrlInput",
                  "MaskedInput", "Rating"}

# Labels that say nothing about what to drop in the zone.
_GENERIC_UPLOAD_LABELS = {"file", "upload", "attachment"}
_GENERIC_SUBMIT_LABELS = {"save", "submit", "create", "savechanges"}

# Containers that may be reduced to decorative shells by the prune, and
# the purely-presentational node types that don't justify keeping one.
_SHELL_TYPES = {"Card", "Section"}
_CHROME_TYPES = {"Card", "Section", "Stack", "Row", "Grid",
                 "Heading", "Text", "Divider", "Spacer", "Badge", "Icon"}


def _fold(s: Any) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _find_workflow_file(root: Path, name: str) -> Path | None:
    wf_dir = root / "workflows"
    if not wf_dir.is_dir() or not name:
        return None
    direct = wf_dir / f"{name}.json"
    if direct.is_file():
        return direct
    target = _fold(name)
    for p in wf_dir.glob("*.json"):
        if _fold(p.stem) == target:
            return p
    return None


def _workflow_nodes(wf: dict) -> list[dict]:
    defn = wf.get("definition") if isinstance(wf.get("definition"), dict) \
        else wf
    nodes = defn.get("nodes")
    return nodes if isinstance(nodes, list) else []


def _node_config(node: dict) -> dict:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    cfg = data.get("config")
    return cfg if isinstance(cfg, dict) else {}


def _referenced_bindings(wf: dict) -> set[str]:
    return set(_BINDING_RE.findall(json.dumps(wf)))


def _produced_vars(wf: dict) -> set[str]:
    """Folded names of variables the workflow's own steps produce — a
    form control for one of these is output rendered as input."""
    produced: set[str] = set()
    for node in _workflow_nodes(wf):
        cfg = _node_config(node)
        for key in ("outputVar", "outputVariable"):
            val = cfg.get(key)
            if isinstance(val, str) and val:
                produced.add(_fold(val))
        fields = cfg.get("aiExtractFields")
        if isinstance(fields, list):
            produced.update(_fold(f) for f in fields if isinstance(f, str))
    return produced


def _humanize_workflow(name: str) -> str:
    """ProcessDocumentWorkflow → 'Process Document'."""
    stem = re.sub(r"(?i)workflow$", "", str(name or "")).strip()
    words = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", stem)
    return " ".join(w.capitalize() for w in words) or "Submit"


def _first_insert_values(wf: dict) -> dict | None:
    for node in _workflow_nodes(wf):
        cfg = _node_config(node)
        if cfg.get("actionType") == "db_insert" and \
                isinstance(cfg.get("values"), dict):
            return cfg["values"]
    return None


def _rewrite_workflow_values(wf: dict, user_fk_cols: set[str]) -> bool:
    """$user.id for removed user-FKs; $now/$today for {{now}}/{{today}}."""
    dirty = False
    for node in _workflow_nodes(wf):
        cfg = _node_config(node)
        values = cfg.get("values")
        if not isinstance(values, dict):
            continue
        for col, val in list(values.items()):
            if not isinstance(val, str):
                continue
            m = _BINDING_RE.fullmatch(val.strip())
            ref = m.group(1) if m else None
            if ref and _fold(col) in user_fk_cols:
                values[col] = "$user.id"
                dirty = True
            elif ref in ("now", "today"):
                values[col] = f"${ref}"
                dirty = True
    return dirty


_DERIVED_NAME_CLASSES = _FILENAME_COLS | _MIME_COLS | _SIZE_COLS


def _collect_in_subtree(node: dict, node_type: str, out: list[dict]) -> None:
    if node.get("type") == node_type:
        out.append(node)
    for child in (node.get("children") or []):
        if isinstance(child, dict):
            _collect_in_subtree(child, node_type, out)


def _primary_upload(form: dict) -> dict | None:
    """The FileUpload carrying the FILE column — not a mis-promoted
    derived-metadata column (an earlier repair can render fileMimeType
    as a second FileUpload; that one is never the primary)."""
    uploads: list[dict] = []
    _collect_in_subtree(form, "FileUpload", uploads)
    for u in uploads:
        name = (u.get("props") or {}).get("name")
        if isinstance(name, str) and _fold(name) not in _DERIVED_NAME_CLASSES:
            return u
    return uploads[0] if uploads else None


def _rewrite_form(form: dict, wf: dict) -> tuple[bool, set[str]]:
    """Returns (changed, user_fk_cols_removed).

    Controls may be nested in layout containers (Form > Grid > Input),
    so the search and the pruning both walk the whole form subtree.
    """
    upload = _primary_upload(form)
    if upload is None:
        return False, set()

    insert_values = _first_insert_values(wf) or {}
    referenced = _referenced_bindings(wf)
    produced = _produced_vars(wf)
    changed = False

    # 1. Companion-field wiring — align hidden-input names to the real
    #    columns the insert binds.
    up_props = upload.setdefault("props", {})
    filename_col = next((c for c in insert_values
                         if _fold(c) in _FILENAME_COLS), None)
    mime_col = next((c for c in insert_values if _fold(c) in _MIME_COLS),
                    None)
    if filename_col and up_props.get("filenameField") != filename_col:
        up_props["filenameField"] = filename_col
        changed = True
    if mime_col and up_props.get("mimeTypeField") != mime_col:
        up_props["mimeTypeField"] = mime_col
        changed = True

    # Drop-zone label: "File Path" is the storage column, not a label.
    up_label = up_props.get("label")
    if not up_label or _fold(up_label) == _fold(up_props.get("name")) or \
            _fold(up_label) in _GENERIC_UPLOAD_LABELS:
        if up_label != "Upload document":
            up_props["label"] = "Upload document"
            changed = True

    # Submit coherence: this form triggers a workflow — the CRUD
    # scaffold's data onSubmit and its generic "Save" label contradict
    # that.
    f_props = form.setdefault("props", {})
    on_submit = f_props.get("onSubmit")
    if isinstance(on_submit, dict) and on_submit.get("kind") == "data":
        f_props.pop("onSubmit")
        changed = True
    submit_label = f_props.get("submitLabel")
    if not submit_label or _fold(submit_label) in _GENERIC_SUBMIT_LABELS:
        action_label = _humanize_workflow(f_props.get("workflow"))
        if submit_label != action_label:
            f_props["submitLabel"] = action_label
            changed = True

    # 2 + 3. Drop derived/system/dead controls — anywhere in the subtree.
    derived = ({_fold(filename_col)} if filename_col else set()) | \
              ({_fold(mime_col)} if mime_col else set()) | _SIZE_COLS
    user_fks: set[str] = set()

    def _should_drop(child: dict) -> bool:
        nonlocal changed
        if child.get("type") == "FileUpload" and child is not upload:
            name = (child.get("props") or {}).get("name")
            if isinstance(name, str) and \
                    _fold(name) in _DERIVED_NAME_CLASSES | derived:
                # a derived-metadata column mis-rendered as an upload
                changed = True
                return True
            return False
        if child.get("type") not in _CONTROL_TYPES:
            return False
        name = (child.get("props") or {}).get("name")
        if not isinstance(name, str):
            return False
        folded = _fold(name)
        if folded in derived or folded == "id" or _LIFECYCLE_RE.match(name):
            changed = True
            return True
        if _USER_FK_RE.search(name):
            user_fks.add(folded)
            changed = True
            return True
        if folded in produced:
            # a workflow step's own output rendered as an editable
            # control — the AI/OCR produces this, the user never types it
            changed = True
            return True
        if name not in referenced:
            # never consumed by the workflow — dead input
            changed = True
            return True
        return False

    def _prune(node: dict) -> None:
        kids = node.get("children")
        if not isinstance(kids, list):
            return
        node["children"] = [c for c in kids
                            if not (isinstance(c, dict) and _should_drop(c))]
        for c in node["children"]:
            if isinstance(c, dict):
                _prune(c)

    _prune(form)

    # Shell cleanup — a Card/Section whose controls we just removed is
    # left as heading-only chrome; drop it rather than shipping a
    # decorative box. Bottom-up so a container of emptied containers
    # also collapses.
    def _is_chrome_only(node: dict) -> bool:
        if node.get("type") not in _CHROME_TYPES:
            return False
        return all(isinstance(c, dict) and _is_chrome_only(c)
                   for c in (node.get("children") or []))

    def _drop_shells(node: dict) -> None:
        nonlocal changed
        kids = node.get("children")
        if not isinstance(kids, list):
            return
        for c in kids:
            if isinstance(c, dict):
                _drop_shells(c)
        kept_kids = [c for c in kids
                     if not (isinstance(c, dict)
                             and c.get("type") in _SHELL_TYPES
                             and _is_chrome_only(c))]
        if len(kept_kids) != len(kids):
            changed = True
            node["children"] = kept_kids

    _drop_shells(form)
    return changed, user_fks


def apply_file_first_forms(output_dir: str | Path) -> dict:
    """Rewrite workflow-bound upload forms to be file-first. Never raises."""
    root = Path(output_dir)
    report: dict[str, Any] = {
        "rewritten": [],
        "summary": {"forms_rewritten": 0, "workflows_rewritten": 0}}
    schemas = root / "src" / "schemas"
    if not schemas.is_dir():
        return report

    for page_path in sorted(schemas.rglob("*.json")):
        doc = _load_json(page_path)
        if not isinstance(doc, dict):
            continue
        page_dirty = False

        def _walk(node: Any) -> None:
            nonlocal page_dirty
            if not isinstance(node, dict):
                return
            if node.get("type") == "Form":
                wf_name = (node.get("props") or {}).get("workflow")
                wf_path = _find_workflow_file(root, wf_name or "")
                wf = _load_json(wf_path) if wf_path else None
                if isinstance(wf, dict):
                    changed, user_fks = _rewrite_form(node, wf)
                    if changed:
                        page_dirty = True
                        report["rewritten"].append(
                            {"page": page_path.name, "workflow": wf_name})
                        report["summary"]["forms_rewritten"] += 1
                    if _rewrite_workflow_values(wf, user_fks):
                        wf_path.write_text(
                            json.dumps(wf, indent=2) + "\n",
                            encoding="utf-8")
                        report["summary"]["workflows_rewritten"] += 1
            for child in (node.get("children") or []):
                _walk(child)

        _walk(doc.get("root"))
        if page_dirty:
            page_path.write_text(json.dumps(doc, indent=2) + "\n",
                                 encoding="utf-8")
    return report
