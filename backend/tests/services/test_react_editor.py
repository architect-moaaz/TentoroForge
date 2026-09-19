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
