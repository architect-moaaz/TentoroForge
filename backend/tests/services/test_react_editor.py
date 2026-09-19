"""The visual React editor: a page read by a parser, edited at spans, checked
before it is saved, versioned in its own history, and changed by Smith only
within the selection."""
from __future__ import annotations

import json

import pytest

from services.blueprint.service import BlueprintService
from services.blueprint.ui_engineer import typecheck  # noqa: F401 — patched by name below
from services.react_editor import adapter, diagnostics, service, smith
from services.react_editor.adapter import AdapterError, revision_of
from services.react_editor.registry import COMPONENTS, component_for
from services.react_editor.service import EditorError

VIEW = '''"use client";
import { Button } from "@/components/ui/button";
import { WorkflowButton } from "@/sdk/client";
import { workflows } from "@/sdk";

export default function View({ rows }: Props) {
  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Records</h1>
      <p className="text-sm text-muted-foreground">Everything on file.</p>
      {rows.length === 0 && <p className="text-sm">Nothing yet</p>}
      <ul>
        {rows.map((r) => (
          <li key={r.id}>{r.name}</li>
        ))}
      </ul>
      <Button variant="outline" onClick={() => go()}>Add</Button>
      <WorkflowButton workflow={workflows.closeCase} input={{ case: "1" }}>Close</WorkflowButton>
    </div>
  );
}
'''
LOAD = '''import { list, type PageContext } from "@/sdk/server";
export async function load(ctx: PageContext) {
  const rows = await list("Case");
  return { rows, total: rows.length };
}
'''


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------

def test_the_model_reads_the_page_with_a_parser_and_stable_ids():
    m = adapter.model(VIEW, LOAD)
    assert [r["owner"] for r in m["roots"]] == ["View"]
    root = m["nodes"]["r0"]
    assert root["type"] == "div" and root["kind"] == "element"
    assert [m["nodes"][c]["type"] for c in root["children"]] == ["h1", "p", "p", "ul", "Button", "WorkflowButton"]
    assert m["nodes"]["r0.0"]["text"] == "Records" and m["nodes"]["r0.0"]["textEditable"]
    assert m["nodes"]["r0.2"]["context"] == "conditional", "a child behind `&&` is still a child, marked"
    assert m["nodes"]["r0.3.0"]["context"] == "repeat" and m["nodes"]["r0.3.0"]["textEditable"] is False
    assert m["nodes"]["r0.3"]["text"] is None, "a list's rows are children, not its text"
    assert {p["name"]: p["kind"] for p in m["nodes"]["r0.4"]["props"]} == {"variant": "string", "onClick": "expr"}
    assert m["loadKeys"] == ["rows", "total"] and m["viewProps"] == ["rows"]


def test_ops_splice_only_the_named_span_and_leave_the_rest_byte_for_byte():
    out = adapter.patch(VIEW, [
        {"op": "setText", "id": "r0.0", "text": "All records"},
        {"op": "setProp", "id": "r0.4", "name": "variant", "value": {"kind": "string", "value": "secondary"}},
        {"op": "setProp", "id": "r0.4", "name": "size", "value": {"kind": "string", "value": "sm"}},
        {"op": "setClasses", "id": "r0.1", "classes": "text-base text-foreground"},
    ])
    assert '<h1 className="text-2xl font-semibold">All records</h1>' in out
    assert '<Button size="sm" variant="secondary" onClick={() => go()}>Add</Button>' in out, "the handler survives"
    assert '<p className="text-base text-foreground">Everything on file.</p>' in out
    # Nothing else moved: the untouched lines are identical.
    for line in ("import { workflows } from \"@/sdk\";", "        {rows.map((r) => (", "          <li key={r.id}>{r.name}</li>"):
        assert line in out


def test_structural_ops_insert_move_remove_duplicate_and_keep_the_page_parseable():
    out = adapter.patch(VIEW, [
        {"op": "insert", "parentId": "r0", "index": 1, "jsx": '<p className="text-sm">Inserted</p>'},
        {"op": "remove", "ids": ["r0.3"]},          # the conditional line, wrapper and all
        {"op": "move", "id": "r0.5", "parentId": "r0", "index": 0},
        {"op": "duplicate", "id": "r0.1"},
        {"op": "addImport", "source": "@/components/ui/card", "names": ["Card"]},
        {"op": "addImport", "source": "@/components/ui/button", "names": ["buttonVariants"]},
    ])
    m = adapter.model(out)
    kids = [m["nodes"][c]["type"] for c in m["nodes"]["r0"]["children"]]
    # Ids are re-derived after every op: once a paragraph is inserted at index
    # 1, `r0.3` is the conditional line and `r0.5` the WorkflowButton; once
    # that is moved first, `r0.1` is the heading. A client therefore sends one
    # structural op per transaction.
    assert kids == ["WorkflowButton", "h1", "h1", "p", "p", "ul", "Button"]
    assert "{rows.length === 0 &&" not in out, "removing a conditional child removes its whole expression"
    assert 'import { Button, buttonVariants } from "@/components/ui/button";' in out
    assert 'import { Card } from "@/components/ui/card";' in out


def test_the_adapter_refuses_what_would_break_the_page_in_plain_words():
    with pytest.raises(AdapterError) as e:
        adapter.patch(VIEW, [{"op": "move", "id": "r0", "parentId": "r0.3"}])
    assert e.value.code == "circular"
    with pytest.raises(AdapterError) as e:
        adapter.patch(VIEW, [{"op": "setText", "id": "r0.3.0", "text": "x"}])
    assert e.value.code == "mixed-text" and "ask Smith" in str(e.value)
    with pytest.raises(AdapterError) as e:
        adapter.patch(VIEW, [{"op": "replaceNode", "id": "r0.0", "jsx": "<h1>"}])
    assert e.value.code == "syntax"
    with pytest.raises(AdapterError) as e:
        adapter.patch(VIEW, [{"op": "setText", "id": "r9", "text": "x"}])
    assert e.value.code == "missing-target"


def test_a_name_imported_from_anywhere_is_not_imported_twice():
    src = VIEW.replace('import { workflows } from "@/sdk";', 'import { widgets, workflows } from "@/sdk/widgets";')
    out = adapter.patch(src, [{"op": "addImport", "source": "@/sdk", "names": ["widgets", "pages"]},
                              {"op": "addImport", "source": "next/link", "names": ["default:Link"]}])
    assert out.count("widgets") == src.count("widgets"), "already bound, from another module"
    assert 'import { pages } from "@/sdk";' in out and 'import Link from "next/link";' in out


def test_dynamic_classes_are_edited_at_their_static_literal_or_refused():
    src = VIEW.replace('className="text-sm text-muted-foreground"', 'className={cn("text-sm", muted && "text-muted-foreground")}')
    out = adapter.patch(src, [{"op": "setClasses", "id": "r0.1", "classes": "text-lg"}])
    assert 'className={cn("text-lg", muted && "text-muted-foreground")}' in out
    src2 = VIEW.replace('className="text-sm text-muted-foreground"', 'className={styles[kind]}')
    with pytest.raises(AdapterError) as e:
        adapter.patch(src2, [{"op": "setClasses", "id": "r0.1", "classes": "text-lg"}])
    assert e.value.code == "dynamic-classes"


def test_annotation_marks_every_element_with_its_id_and_changes_nothing_else():
    out = adapter.annotate(VIEW)
    assert '<h1 data-fid="r0.0" className="text-2xl font-semibold">Records</h1>' in out
    assert '<li data-fid="r0.3.0" key={r.id}>{r.name}</li>' in out
    stripped = out.replace(' data-fid="', "\0").split("\0")
    assert len(stripped) == 1 + len(adapter.model(VIEW)["nodes"])
    # Stripping the ids gives the original back, so the running copy is the Blueprint's plus ids.
    import re
    assert re.sub(r' data-fid="[^"]*"', "", out) == VIEW


def test_a_revision_is_the_content():
    assert revision_of(VIEW, LOAD) == revision_of(VIEW, LOAD)
    assert revision_of(VIEW, LOAD) != revision_of(VIEW + " ", LOAD)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def test_the_compilers_words_become_a_persons():
    f = diagnostics.finding("view.tsx(12,7): error TS2322: Type '\"big\"' is not assignable to type '\"sm\" | \"lg\" | undefined'.")
    assert f["line"] == 12 and f["file"] == "view.tsx" and f["code"] == "TS2322"
    assert f["plain"].startswith("Line 12 of the page: \"big\" is not something the app accepts here")
    f = diagnostics.finding("view.tsx(3,1): error TS2304: Cannot find name 'Card'.")
    assert "does not have yet" in f["plain"] and "Ask Smith" in f["plain"]
    f = diagnostics.finding("load.ts(4,10): error TS2339: Property 'nam' does not exist on type 'Case'.")
    assert f["plain"] == "Line 4 of what the page loads: “nam” is not something this page's data has."


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def test_the_registry_names_things_by_outcome_and_recognises_a_pages_elements():
    assert component_for("Button")["label"] == "Button"
    assert component_for("h2")["id"] == "heading"
    assert component_for("WorkflowButton")["settings"][0]["label"] == "Text"
    labels = {s["label"] for c in COMPONENTS for s in c["settings"] if s["section"] == "simple"}
    for technical in ("className", "variant", "props", "href", "onClick"):
        assert technical not in labels, "simple settings never show implementation names"
    assert component_for("Button")["events"][0]["label"] == "What happens when clicked?"
    assert next(c for c in COMPONENTS if c["id"] == "file-input")["status"] == "unsupported"


# ---------------------------------------------------------------------------
# The service — open, apply, history, restore
# ---------------------------------------------------------------------------

def _project(tmp_path, monkeypatch, *, findings=None):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "All Cases", "route": "/cases", "purpose": "Every case."},
                        {"id": "PAGE-002", "name": "Home", "route": "/", "purpose": "Start."}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": LOAD, "view": VIEW}]
    svc.doc["workflows"] = [{"id": "FLOW-001", "name": "Close Case", "trigger": {"kind": "manual"},
                             "inputs": [{"name": "case", "kind": "record", "entity": "ENTITY-001", "required": True}],
                             "launchedFrom": ["PAGE-001"]}]
    svc.save()
    app = tmp_path / "app"
    (app / "src/app/(dashboard)/cases").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    calls = []

    def fake_check(doc, project, page_id, view, load):
        calls.append((page_id, view, load))
        return list(findings or [])
    monkeypatch.setattr(service, "_check", fake_check)
    # The app's files are projected on write; keep the projection but not the scaffold's sweep.
    return service.locate(tmp_path), calls


def test_open_gives_the_model_the_source_the_revision_and_a_baseline_in_history(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    out = service.open_page(project, "PAGE-001")
    assert out["coded"] and out["revision"] == revision_of(VIEW, LOAD)
    assert out["model"]["nodes"]["r0.0"]["text"] == "Records"
    assert out["pages"][1]["key"] == "home" and out["workflows"][0]["key"] == "closeCase"
    assert out["workflows"][0]["inputs"][0]["required"] is True
    assert [h["kind"] for h in out["history"]] == ["baseline"]
    annotated = (tmp_path / "app/src/app/(dashboard)/cases/view.tsx").read_text()
    assert 'data-fid="r0.0"' in annotated, "the running copy carries the ids"
    assert 'data-fid' not in service.load_blueprint(project).doc["pageCode"][0]["view"], "the Blueprint's does not"

    plain = service.open_page(project, "PAGE-002")
    assert plain["coded"] is False and "Ask Smith" in plain["reason"]


def test_apply_checks_writes_through_the_blueprint_and_records_history(tmp_path, monkeypatch):
    project, calls = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    out = service.apply(project, "PAGE-001", base_revision=rev0, label="Rename heading",
                        ops=[{"op": "setProp", "id": "r0.4", "name": "variant", "value": {"kind": "string", "value": "secondary"}}])
    assert out["checked"] is True and calls, "a prop change is checked by the compiler"
    assert out["revision"] != rev0
    svc = service.load_blueprint(project)
    assert 'variant="secondary"' in svc.doc["pageCode"][0]["view"]
    assert svc.doc["version"] == out["version"] and svc.doc["version"] > 1, "the Blueprint versioned it"
    assert (tmp_path / "app/src/app/(dashboard)/cases/view.tsx").read_text().count("data-fid") > 5
    hist = service.history(project, "PAGE-001")
    assert [h["label"] for h in hist] == ["Built by Forge", "Rename heading"]
    assert hist[-1]["parent"] == rev0 and hist[-1]["revision"] == out["revision"]


def test_text_and_class_changes_skip_the_compiler(tmp_path, monkeypatch):
    project, calls = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    out = service.apply(project, "PAGE-001", base_revision=rev0,
                        ops=[{"op": "setText", "id": "r0.0", "text": "Cases"},
                             {"op": "setClasses", "id": "r0.0", "classes": "text-3xl font-bold"}])
    assert out["checked"] is False and not calls
    assert out["model"]["nodes"]["r0.0"]["text"] == "Cases"


def test_a_stale_transaction_is_refused_with_the_current_revision(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    rev1 = service.apply(project, "PAGE-001", base_revision=rev0, ops=[{"op": "setText", "id": "r0.0", "text": "A"}])["revision"]
    with pytest.raises(EditorError) as e:
        service.apply(project, "PAGE-001", base_revision=rev0, ops=[{"op": "setText", "id": "r0.0", "text": "B"}])
    assert e.value.status == 409 and e.value.code == "stale" and e.value.extra["current"] == rev1
    assert "A" == adapter.model(service.load_blueprint(project).doc["pageCode"][0]["view"])["nodes"]["r0.0"]["text"]


def test_a_change_that_does_not_compile_is_not_saved(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch,
                          findings=[{"file": "view.tsx", "line": 9, "code": "TS2322", "raw": "x",
                                     "plain": "Line 9 of the page: not accepted", "severity": "must-fix"}])
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    with pytest.raises(EditorError) as e:
        service.apply(project, "PAGE-001", base_revision=rev0,
                      ops=[{"op": "setProp", "id": "r0.4", "name": "size", "value": {"kind": "string", "value": "huge"}}])
    assert e.value.status == 422 and e.value.extra["findings"][0]["plain"].startswith("Line 9")
    assert service.open_page(project, "PAGE-001")["revision"] == rev0, "the last valid page stands"


def test_restore_brings_back_a_recorded_revision_without_recompiling(tmp_path, monkeypatch):
    project, calls = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    rev1 = service.apply(project, "PAGE-001", base_revision=rev0, ops=[{"op": "setText", "id": "r0.0", "text": "Gone"}])["revision"]
    out = service.restore(project, "PAGE-001", revision=rev0, expected=rev1)
    assert out["revision"] == rev0 and out["checked"] is False and not calls
    assert service.history(project, "PAGE-001")[-1]["kind"] == "restore"
    with pytest.raises(EditorError) as e:
        service.restore(project, "PAGE-001", revision="nope", expected=rev0)
    assert e.value.status == 404


def test_pages_lists_what_is_coded_and_the_entry_page(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    out = service.pages(service.load_blueprint(project).doc)
    assert out["entryPage"] == "PAGE-002"
    assert {p["id"]: p["coded"] for p in out["pages"]} == {"PAGE-001": True, "PAGE-002": False}


# ---------------------------------------------------------------------------
# Smith
# ---------------------------------------------------------------------------

class _Client:
    model = "fake"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, *, system, user, schema):
        self.calls.append((system, user))
        return json.dumps(self.reply)


def _reply(**kw):
    base = {"summary": "The button is now secondary.", "explanation": "It steps back visually.",
            "replacements": [], "imports": [], "needs": [], "questions": []}
    base.update(kw)
    return base


def test_smith_is_given_the_selection_and_answers_with_a_scoped_staged_proposal(tmp_path, monkeypatch):
    project, calls = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    client = _Client(_reply(replacements=[{"nodeId": "r0.4", "jsx": '<Button variant="secondary" onClick={() => go()}>Add a record</Button>'}]))
    p = smith.propose(project, "PAGE-001", base_revision=rev0, prompt="make this button quieter",
                      selection={"type": "component", "nodeIds": ["r0.4"]}, annotation="only this one",
                      client=client)
    system, user = client.calls[0]
    assert "editing ONE PART" in system and "## r0.4 — <Button>" in user and "only this one" in user
    assert "Ancestors you may extend to" in user and "- r0:" in user
    assert p["status"] == "ready" and p["valid"] and p["baseRevision"] == rev0
    assert p["replacements"][0]["before"].startswith("<Button variant=\"outline\"")
    assert "viewAfter" not in p, "the staged source stays server-side"
    assert calls, "the proposal was checked by the compiler before it was offered"

    out = smith.apply_proposal(project, "PAGE-001", p["id"], base_revision=rev0)
    assert out["revision"] != rev0 and out["proposal"]["status"] == "applied"
    view = service.load_blueprint(project).doc["pageCode"][0]["view"]
    assert "Add a record" in view and "workflows.closeCase" in view, "the rest of the page is intact"
    assert service.history(project, "PAGE-001")[-1]["kind"] == "smith"
    again = smith.apply_proposal(project, "PAGE-001", p["id"], base_revision=out["revision"])
    assert again.get("alreadyApplied"), "applying twice is one change"


def test_a_proposal_outside_the_selection_is_refused_and_an_ancestor_needs_consent(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    client = _Client(_reply(replacements=[
        {"nodeId": "r0", "jsx": '<div className="grid gap-4 md:grid-cols-2"><h1>Records</h1></div>'},
        {"nodeId": "r0.5", "jsx": "<span>nope</span>"},
    ]))
    p = smith.propose(project, "PAGE-001", base_revision=rev0, prompt="two columns",
                      selection={"type": "region", "nodeIds": ["r0.0", "r0.1"]}, client=client)
    assert p["expandsScope"] == ["r0"] and p["refused"][0]["nodeId"] == "r0.5"
    with pytest.raises(EditorError) as e:
        smith.apply_proposal(project, "PAGE-001", p["id"], base_revision=rev0)
    assert e.value.code == "scope"
    out = smith.apply_proposal(project, "PAGE-001", p["id"], base_revision=rev0, allow_scope_expansion=True)
    assert "md:grid-cols-2" in service.load_blueprint(project).doc["pageCode"][0]["view"]
    assert "nope" not in service.load_blueprint(project).doc["pageCode"][0]["view"]


def test_a_stale_proposal_is_detected_and_never_applied_silently(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    client = _Client(_reply(replacements=[{"nodeId": "r0.0", "jsx": "<h1>Smith's title</h1>"}]))
    p = smith.propose(project, "PAGE-001", base_revision=rev0, prompt="retitle",
                      selection={"nodeIds": ["r0.0"]}, client=client)
    rev1 = service.apply(project, "PAGE-001", base_revision=rev0, ops=[{"op": "setText", "id": "r0.0", "text": "Mine"}])["revision"]
    with pytest.raises(EditorError) as e:
        smith.apply_proposal(project, "PAGE-001", p["id"], base_revision=rev1)
    assert e.value.code == "stale"
    assert adapter.model(service.load_blueprint(project).doc["pageCode"][0]["view"])["nodes"]["r0.0"]["text"] == "Mine"


def test_an_ambiguous_request_comes_back_as_choices_and_an_invalid_one_cannot_be_applied(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    client = _Client(_reply(questions=[{"question": "Quieter how?", "options": ["Outlined", "Plain text"]}]))
    p = smith.propose(project, "PAGE-001", base_revision=rev0, prompt="quieter",
                      selection={"nodeIds": ["r0.4"]}, client=client)
    assert p["status"] == "needs-choice" and p["questions"][0]["options"] == ["Outlined", "Plain text"]

    monkeypatch.setattr(service, "_check", lambda *a: [{"file": "view.tsx", "line": 1, "code": "TS1", "raw": "x",
                                                         "plain": "Line 1 of the page: broken", "severity": "must-fix"}])
    client = _Client(_reply(replacements=[{"nodeId": "r0.4", "jsx": "<Button>Bad</Button>"}]))
    p = smith.propose(project, "PAGE-001", base_revision=rev0, prompt="x", selection={"nodeIds": ["r0.4"]}, client=client)
    assert p["status"] == "invalid" and p["findings"][0]["plain"].startswith("Line 1")
    with pytest.raises(EditorError) as e:
        smith.apply_proposal(project, "PAGE-001", p["id"], base_revision=rev0)
    assert e.value.code == "invalid-proposal"


def test_a_deleted_target_is_reported_not_guessed(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    rev0 = service.open_page(project, "PAGE-001")["revision"]
    with pytest.raises(EditorError) as e:
        smith.propose(project, "PAGE-001", base_revision=rev0, prompt="x", selection={"nodeIds": ["r0.99"]},
                      client=_Client(_reply()))
    assert e.value.code == "deleted-target"


# ---------------------------------------------------------------------------
# The JIT renderer — a page bundled against a small app, no dev server
# ---------------------------------------------------------------------------

def _jit_app(tmp_path):
    """A minimal generated app: the SDK's fixed files, a kit-less page, and the
    repository's node_modules (esbuild, react, sonner) standing in for the
    app's own."""
    import os
    from services.react_editor import jit
    app = tmp_path / "app"
    (app / "src/sdk").mkdir(parents=True)
    (app / "src/components").mkdir(parents=True)
    (app / "src/app/cases").mkdir(parents=True)
    (app / "package.json").write_text('{"name": "t", "private": true}')
    (app / "tsconfig.json").write_text('{"compilerOptions": {"jsx": "preserve", "paths": {"@/*": ["./src/*"]}, "baseUrl": "."}}')
    os.symlink(jit.SCRIPT.parents[2] / "node_modules", app / "node_modules")
    (app / "src/sdk/schema.ts").write_text("export interface Case { id: string; title: string; status: string; amount: number }\n"
                                           "export interface Entities { Case: Case }\nexport type EntityName = keyof Entities & string;\n")
    (app / "src/sdk/frame.tsx").write_text('"use client";\nimport type { ReactNode } from "react";\nimport { useRouter } from "next/navigation";\n'
                                           "export function PageFrame({ entities, children }: { entities: string[]; children: ReactNode }) { useRouter(); return <main id=\"main\">{children}</main>; }\n")
    (app / "src/components/PublicPageFrame.tsx").write_text('import Link from "next/link";\nimport type * as React from "react";\n'
                                                            'export function PublicPageFrame({ children }: { children: React.ReactNode }) { return <><header><Link href="/">Home</Link></header>{children}</>; }\n')
    return app


def test_the_jit_bundles_a_page_with_sample_data_and_no_dev_server(tmp_path, monkeypatch):
    from services.react_editor import jit
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Cases", "route": "/cases", "purpose": "x", "access": "public"}]
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Case", "table": "cases", "fields": [
        {"name": "id", "type": "uuid"}, {"name": "title", "type": "string"},
        {"name": "status", "type": "string", "enumValues": ["Open", "Closed"]}, {"name": "amount", "type": "decimal"}]}]}
    svc.doc["pageCode"] = [{"page": "PAGE-001",
        "load": 'import { list, count, type PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return { rows: await list("Case", { sort: "title" }), open: await count("Case", { status: "Open" }) }; }\n',
        "view": '"use client";\nimport Link from "next/link";\nimport type { load } from "./load";\ntype Props = NonNullable<Awaited<ReturnType<typeof load>>>;\n'
                'export default function View({ rows, open }: Props) { return <div className="p-6"><h1>All cases ({open} open)</h1><ul>{rows.map((r) => <li key={r.id}><Link href={`/cases/${r.id}`}>{r.title}</Link> {r.amount}</li>)}</ul></div>; }\n'}]
    svc.save()
    _jit_app(tmp_path)
    project = service.locate(tmp_path)
    shared = jit.vendor(project)
    assert shared["cached"] is False and "react" in shared["specifiers"] and "react/jsx-runtime" in shared["specifiers"]
    assert "sonner" in shared["specifiers"] and "next/link" not in shared["specifiers"], "Next's modules are shimmed, never vendored"
    assert "window.__forgeVendor" in shared["js"] and len(shared["js"]) > 100_000, "one script carries React and the rest"
    assert jit.vendor(project)["cached"] is True

    out = jit.build(project, "PAGE-001")
    assert out["cached"] is False and out["data"] == "sample" and out["vendorKey"] == shared["key"]
    js = out["js"]
    assert len(js) < 60_000 and "react.development" not in js and "__forgeVendor" in js, "the page carries its own code and reads React from the shared script"
    assert "All cases" in js and "Home" in js, "the page and its public frame are in the bundle"
    assert '"Quarterly review 1"' in js and '"Open"' in js and '"sample-case-1"' in js, "sample rows come from the entity's fields"
    assert "forge-editor:navigate" in js and "forge-editor:action" in js, "moves and workflow runs are reported to the editor"
    assert "pushState" not in js.split("__forgeGo")[1][:2000], "the shims never touch the History API"
    assert (project.app_root / "src/app/cases/view.tsx").read_text().count("data-fid") == 5, "the bundled copy carries the ids"
    again = jit.build(project, "PAGE-001")
    assert again["cached"] is True and again["js"] == js
    # A new revision is a new build.
    service.open_page(project, "PAGE-001", annotate=False)
    rev = service.open_page(project, "PAGE-001")["revision"]
    service.apply(project, "PAGE-001", base_revision=rev, ops=[{"op": "setClasses", "id": "r0.0", "classes": "text-3xl font-bold"}])
    fresh = jit.build(project, "PAGE-001")
    assert fresh["cached"] is False and "text-3xl font-bold" in fresh["js"]


def test_a_page_without_code_or_toolchain_is_refused_plainly(tmp_path, monkeypatch):
    from services.react_editor import jit
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Cases", "route": "/cases", "purpose": "x"}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": LOAD, "view": VIEW}]
    svc.save()
    (tmp_path / "app").mkdir()
    (tmp_path / "app/package.json").write_text("{}")
    with pytest.raises(EditorError) as e:
        jit.build(service.locate(tmp_path), "PAGE-001")
    assert e.value.status == 503 and "not installed" in str(e.value)
    with pytest.raises(EditorError) as e:
        jit.build(service.locate(tmp_path), "PAGE-999")
    assert e.value.code == "no-page"


# ---------------------------------------------------------------------------
# Charts — a widget written through the Blueprint, read in load, drawn in view
# ---------------------------------------------------------------------------

def _chart_project(tmp_path, monkeypatch):
    from services.react_editor import widgets  # noqa: F401 — imported for the monkeypatch below
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Dashboard", "route": "/", "purpose": "Overview."}]
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Order", "table": "orders", "fields": [
        {"name": "id", "type": "uuid"}, {"name": "customer", "type": "string"},
        {"name": "status", "type": "string", "enumValues": ["Open", "Paid"]},
        {"name": "total", "type": "decimal"}, {"name": "placedAt", "type": "datetime"}]}]}
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": 'import { count, type PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) {\n  return {\n    open: await count("Order", { status: "Open" }),\n  };\n}\n',
                            "view": '"use client";\nimport type { load } from "./load";\ntype Props = NonNullable<Awaited<ReturnType<typeof load>>>;\nexport default function View({ open }: Props) {\n  return (\n    <div className="p-6">\n      <h1>Orders</h1>\n    </div>\n  );\n}\n'}]
    svc.save()
    (tmp_path / "app/src/app/_root").mkdir(parents=True)
    (tmp_path / "app/package.json").write_text("{}")
    monkeypatch.setattr(service, "_check", lambda *a: [])
    # The SDK projection wants the scaffold's fixed files; the generated half is what matters here.
    return service.locate(tmp_path)


def test_a_chart_is_a_widget_the_page_reads_and_draws(tmp_path, monkeypatch):
    from services.react_editor import widgets
    project = _chart_project(tmp_path, monkeypatch)
    out = widgets.create(project, "PAGE-001", {"label": "Revenue by status", "kind": "chart", "entity": "Order",
                                                 "measures": [{"aggregation": "sum", "field": "total"}],
                                                 "dimensions": [{"field": "status"}], "mark": "bar", "stacked": True})
    w = out["widget"]
    assert w["id"].startswith("WIDGET-") and w["key"] == "revenueByStatus" and w["chart"] == {"mark": "bar", "stacked": True}
    assert w["source"]["entity"] == "Order" and w["source"]["measures"][0] == {"key": "sum_total", "aggregation": "sum", "field": "total"}
    sdk = (project.app_root / "src/sdk/widgets.ts").read_text()
    assert "revenueByStatus:" in sdk and '"mark": "bar"' in sdk, "the typed handle is regenerated"
    assert service.load_blueprint(project).doc["version"] > 1, "written through the Blueprint, versioned"

    doc = service.open_page(project, "PAGE-001")
    assert doc["widgets"][0]["key"] == "revenueByStatus"
    ops = [{"op": "addImport", "file": "load", "source": "@/sdk/server", "names": ["runWidget"]},
           {"op": "addImport", "file": "load", "source": "@/sdk", "names": ["widgets"]},
           {"op": "addReturnKey", "file": "load", "key": "revenueByStatus", "expr": "await runWidget(widgets.revenueByStatus)"},
           {"op": "addImport", "source": "@/sdk/client", "names": ["WidgetView"]},
           {"op": "addImport", "source": "@/sdk", "names": ["widgets"]},
           {"op": "ensureProp", "name": "revenueByStatus"},
           {"op": "insert", "parentId": "r0", "jsx": "<WidgetView widget={widgets.revenueByStatus} data={revenueByStatus} />"}]
    r = service.apply(project, "PAGE-001", base_revision=doc["revision"], ops=ops, label="Add chart")
    assert r["checked"] is True
    row = service.load_blueprint(project).doc["pageCode"][0]
    assert "revenueByStatus: await runWidget(widgets.revenueByStatus)," in row["load"]
    assert 'import { count, type PageContext, runWidget } from "@/sdk/server";' in row["load"]
    assert "function View({ open, revenueByStatus }: Props)" in row["view"]
    assert "<WidgetView widget={widgets.revenueByStatus} data={revenueByStatus} />" in row["view"]
    assert r["model"]["nodes"]["r0.1"]["type"] == "WidgetView"


def test_a_chart_the_data_cannot_draw_is_refused_before_it_exists(tmp_path, monkeypatch):
    from services.react_editor import widgets
    project = _chart_project(tmp_path, monkeypatch)
    with pytest.raises(EditorError) as e:
        widgets.create(project, "PAGE-001", {"label": "Bad", "kind": "chart", "entity": "Order",
                                              "measures": [{"aggregation": "sum", "field": "customer"}], "dimensions": [{"field": "status"}], "mark": "bar"})
    assert e.value.code == "bad-widget" and "not a number" in str(e.value)
    with pytest.raises(EditorError) as e:
        widgets.create(project, "PAGE-001", {"label": "Bad", "kind": "chart", "entity": "Order",
                                              "measures": [{"aggregation": "count"}], "dimensions": [{"field": "status", "bucket": "month"}], "mark": "line"})
    assert "not a date" in str(e.value)
    with pytest.raises(EditorError) as e:
        widgets.create(project, "PAGE-001", {"label": "Bad", "kind": "chart", "entity": "Order",
                                              "measures": [{"aggregation": "count"}], "dimensions": [], "mark": "pie"})
    assert "pie chart needs 1" in str(e.value)
    assert not service.load_blueprint(project).doc.get("widgets"), "nothing was written"


def test_changing_a_chart_edits_its_definition_and_renaming_it_follows_the_page(tmp_path, monkeypatch):
    from services.react_editor import widgets
    project = _chart_project(tmp_path, monkeypatch)
    w = widgets.create(project, "PAGE-001", {"label": "Orders by status", "kind": "chart", "entity": "Order",
                                              "measures": [{"aggregation": "count"}], "dimensions": [{"field": "status"}], "mark": "bar"})["widget"]
    doc = service.open_page(project, "PAGE-001")
    service.apply(project, "PAGE-001", base_revision=doc["revision"], label="Add chart", ops=[
        {"op": "addImport", "file": "load", "source": "@/sdk/server", "names": ["runWidget"]},
        {"op": "addImport", "file": "load", "source": "@/sdk", "names": ["widgets"]},
        {"op": "addReturnKey", "file": "load", "key": "ordersByStatus", "expr": "await runWidget(widgets.ordersByStatus)"},
        {"op": "addImport", "source": "@/sdk/client", "names": ["WidgetView"]}, {"op": "addImport", "source": "@/sdk", "names": ["widgets"]},
        {"op": "ensureProp", "name": "ordersByStatus"},
        {"op": "insert", "parentId": "r0", "jsx": "<WidgetView widget={widgets.ordersByStatus} data={ordersByStatus} />"}])
    out = widgets.update(project, w["id"], {"mark": "donut", "limit": 5})
    assert out["widget"]["chart"] == {"mark": "donut"} and out["widget"]["source"]["limit"] == 5 and out["renamed"] is None
    rev = service.open_page(project, "PAGE-001")["revision"]
    out = widgets.update(project, w["id"], {"label": "Status mix"}, page_revision=rev)
    assert out["widget"]["key"] == "statusMix" and out["renamed"]["from"] == "ordersByStatus"
    row = service.load_blueprint(project).doc["pageCode"][0]
    assert "widgets.statusMix" in row["view"] and "widgets.statusMix" in row["load"]
    assert "widgets.ordersByStatus" not in row["view"] and "widgets.ordersByStatus" not in row["load"]
    assert "data={ordersByStatus}" in row["view"], "the page's own data key is the person's to rename"
    assert [h["label"] for h in service.history(project, "PAGE-001")][-1] == "Rename chart handle to statusMix"

    assert widgets.remove(project, w["id"])["removed"] is True
    live = [x for x in service.load_blueprint(project).doc["widgets"] if x.get("status") != "DEPRECATED"]
    assert live == [] and "statusMix" not in (project.app_root / "src/sdk/widgets.ts").read_text()


# ---------------------------------------------------------------------------
# Visual data mapping — shapes, rows, and content written from a choice
# ---------------------------------------------------------------------------

def test_the_model_knows_the_shape_of_what_the_page_loads_and_the_row_a_cell_sits_in():
    load = ('import { listPage, record, count, runWidget, type PageContext } from "@/sdk/server";\nimport { widgets } from "@/sdk";\n'
            'export async function load(ctx: PageContext) {\n  const page = await listPage("Case", { page: 1 });\n'
            '  const [open, current] = await Promise.all([count("Case", { status: "Open" }), record("Case", ctx.params.id)]);\n'
            '  const male = await runWidget(widgets.male);\n  return { rows: page.rows, total: page.total, open, current, male, q: ctx.searchParams.q ?? "" };\n}\n')
    view = ('"use client";\nexport default function View(props: Props) {\n  return (\n    <div>\n      <h1>{props.current?.title ?? ""}</h1>\n'
            '      <table><tbody>{props.rows.map((row) => (<tr key={row.id}><td>{String(row.amount ?? "")}</td></tr>))}</tbody></table>\n'
            '      <WorkflowForm workflow={workflows.close} fields={{ note: { label: "Note", kind: "textarea" }, case: { value: props.current?.id } }} />\n    </div>\n  );\n}\n')
    m = adapter.model(view, load)
    assert m["loadShapes"] == {"rows": {"kind": "rows", "entity": "Case"}, "total": {"kind": "number"}, "open": {"kind": "number"},
                               "current": {"kind": "record", "entity": "Case"}, "male": {"kind": "widget", "widget": "male"}, "q": {"kind": "string"}}
    assert m["viewParam"] == {"kind": "identifier", "name": "props"}
    cell = next(n for n in m["nodes"].values() if n["type"] == "td")
    assert cell["exprOnly"] == 'String(row.amount ?? "")'
    row = m["nodes"][cell["parent"]]
    assert row["repeat"] == {"source": "props.rows", "variable": "row"}
    form = next(n for n in m["nodes"].values() if n["type"] == "WorkflowForm")
    fields = form["objects"]["fields"]
    assert [f["key"] for f in fields] == ["note", "case"]
    assert fields[0]["entries"][0] == {"key": "label", "code": '"Note"', "kind": "string", "value": "Note"}
    assert fields[1]["entries"][0]["kind"] == "expr" and fields[1]["entries"][0]["code"] == "props.current?.id"

    out = adapter.patch(view, [
        {"op": "setChildren", "id": next(n["id"] for n in m["nodes"].values() if n["type"] == "h1"), "jsx": "{props.current?.owner ?? \"\"}"},
        {"op": "setObjectProp", "id": form["id"], "name": "fields", "entries": [
            {"key": "note", "kind": "object", "entries": [{"key": "label", "kind": "string", "value": "Your note"}, {"key": "kind", "kind": "string", "value": "textarea"},
                                                          {"key": "options", "kind": "objects", "items": [[{"key": "label", "kind": "string", "value": "A"}, {"key": "value", "kind": "string", "value": "A"}]]}]},
            {"key": "case", "kind": "object", "entries": [{"key": "value", "kind": "expr", "code": "props.current?.id"}]}]},
    ])
    assert '<h1>{props.current?.owner ?? ""}</h1>' in out
    assert 'label: "Your note"' in out and 'kind: "textarea"' in out and 'options: [{ label: "A", value: "A" }]' in out
    assert "case: { value: props.current?.id }" in out
    assert adapter.model(out)["nodes"][form["id"]]["objects"]["fields"][0]["entries"][0]["value"] == "Your note", "rewritten fields read back"


# ---------------------------------------------------------------------------
# Pages and the menu, from the editor
# ---------------------------------------------------------------------------

def _pages_project(tmp_path, monkeypatch):
    from services.react_editor import pages
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Desk", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Home", "route": "/", "purpose": "Start.", "access": "public"},
                        {"id": "PAGE-002", "name": "Cases", "route": "/cases", "purpose": "Every case.", "access": "public"}]
    svc.doc["pageCode"] = [{"page": "PAGE-002", "load": LOAD, "view": VIEW.replace(">Records</h1>", "><Link href={href(pages.home)}>Home</Link></h1>")}]
    svc.doc["navigation"] = {"style": "topbar", "tree": [{"label": "Home", "page": "PAGE-001"}, {"label": "Cases", "page": "PAGE-002"}]}
    svc.save()
    (tmp_path / "app/src/app").mkdir(parents=True)
    (tmp_path / "app/package.json").write_text("{}")
    monkeypatch.setattr(service, "_check", lambda *a: [])
    projected = []
    monkeypatch.setattr(pages, "_reproject", lambda svc, project: projected.append(1) or [])
    monkeypatch.setattr("services.smith.page_change._project", lambda svc, app_root: [])
    return service.locate(tmp_path), projected


def test_a_page_is_made_blank_in_the_menu_and_written_out(tmp_path, monkeypatch):
    from services.react_editor import pages
    project, projected = _pages_project(tmp_path, monkeypatch)
    out = pages.create(project, {"name": "Team members", "menu": True, "access": "public"})
    p = out["page"]
    assert p["id"] == "PAGE-003" and p["route"] == "/team-members" and p["key"] == "teamMembers"
    doc = service.load_blueprint(project).doc
    assert [n["page"] for n in doc["navigation"]["tree"]] == ["PAGE-001", "PAGE-002", "PAGE-003"]
    row = next(r for r in doc["pageCode"] if r["page"] == "PAGE-003")
    assert "Team members" in row["view"] and "export async function load" in row["load"]
    assert projected == [1] and doc["version"] > 1
    opened = service.open_page(project, "PAGE-003")
    assert opened["coded"] and opened["model"]["nodes"]["r0.0.0"]["text"] == "Team members"
    with pytest.raises(EditorError) as e:
        pages.create(project, {"name": "Other", "route": "/cases"})
    assert e.value.code == "route-taken" and "Cases" in str(e.value)
    with pytest.raises(EditorError) as e:
        pages.create(project, {"name": "Bad", "route": "/Not Valid"})
    assert e.value.code == "bad-route"
    listing = service.pages(doc)
    assert listing["navigation"]["tree"][2]["label"] == "Team members"


def test_renaming_a_page_follows_its_handle_across_pages_and_the_menu(tmp_path, monkeypatch):
    from services.react_editor import pages
    project, _ = _pages_project(tmp_path, monkeypatch)
    out = pages.update(project, "PAGE-001", {"name": "Start here"})
    assert out["page"]["key"] == "startHere" and out["renamed"]["from"] == "home"
    doc = service.load_blueprint(project).doc
    assert "pages.startHere" in doc["pageCode"][0]["view"] and "pages.home" not in doc["pageCode"][0]["view"]
    assert doc["navigation"]["tree"][0]["label"] == "Start here"
    with pytest.raises(EditorError) as e:
        pages.update(project, "PAGE-002", {"route": "/"})
    assert e.value.code == "route-taken"


def test_the_menu_is_arranged_and_validated_and_a_page_is_removed_with_its_links(tmp_path, monkeypatch):
    from services.react_editor import pages
    project, _ = _pages_project(tmp_path, monkeypatch)
    out = pages.set_navigation(project, {"tree": [{"label": "All cases", "page": "PAGE-002"}, {"label": "Home", "page": "PAGE-001"}], "initialRoute": "/cases"})
    assert [n["label"] for n in out["navigation"]["tree"]] == ["All cases", "Home"] and out["navigation"]["initialRoute"] == "/cases"
    doc = service.load_blueprint(project).doc
    assert next(p for p in doc["pages"] if p["id"] == "PAGE-002")["entry"] is True
    with pytest.raises(EditorError) as e:
        pages.set_navigation(project, {"tree": [{"label": "Ghost", "page": "PAGE-009"}]})
    assert e.value.code == "bad-menu" and "not a page" in str(e.value)

    c = pages.consequences(project, "PAGE-001")
    assert c["refusal"] is None
    out = pages.remove(project, "PAGE-001")
    assert out["removed"] is True
    doc = service.load_blueprint(project).doc
    assert next(p for p in doc["pages"] if p["id"] == "PAGE-001")["status"] == "DEPRECATED"
    assert [n["page"] for n in doc["navigation"]["tree"]] == ["PAGE-002"], "its menu entry went with it"
