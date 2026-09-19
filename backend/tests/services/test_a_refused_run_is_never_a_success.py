"""A form's feedback tells the truth — h7gmi93x, 2026-09-19.

Submitting Add Data empty showed "Record added successfully.": the workflow's
validation branch saved nothing, but both of its ends completed alike, and the
page could not tell them apart. Behind it: no toast was ever mounted, the form
marked no field required, it kept the saved values, and a signed-in person was
refused every workflow a public page runs. Each is held here at the piece of
the generator that produced it, so the next generation cannot ship it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_ROOT = _BACKEND.parent
_TEMPLATES = _BACKEND / "templates"


def _tsx() -> Path | None:
    tsx = _ROOT / "node_modules" / ".bin" / "tsx"
    return tsx if tsx.exists() and shutil.which("node") else None


@pytest.mark.skipif(_tsx() is None, reason="tsx is not installed")
def test_the_engine_reports_a_refused_end_as_a_failure_with_its_message(tmp_path):
    """The real engine, not a copy of its logic: the success end completes,
    the refused end fails with its own sentence, its template filled."""
    engine = _TEMPLATES / "runtime" / "workflows" / "engine.ts"
    script = tmp_path / "run.mts"
    script.write_text(f'''
import * as mod from {json.dumps(str(engine))};
const {{ executeWorkflow }} = ((mod as any).executeWorkflow ? mod : (mod as any).default) as any;
const node = (id: string, type: string, config: Record<string, unknown> = {{}}) =>
  ({{ id, type, position: {{ x: 0, y: 0 }}, data: {{ label: id, nodeType: type, config }} }});
const wf: any = {{ id: "create-record", name: "Create Record", definition: {{ trigger: {{}}, nodes: [
  node("trigger", "trigger"),
  node("check", "condition", {{ expression: "age >= 1" }}),
  node("ok", "end", {{ refused: false }}),
  node("bad", "end", {{ refused: true, message: "Age must be between 1 and {{{{max}}}}." }}),
], edges: [
  {{ id: "e1", source: "trigger", target: "check" }},
  {{ id: "e2", source: "check", target: "ok", data: {{ edgeType: "then" }}, sourceHandle: "then" }},
  {{ id: "e3", source: "check", target: "bad", data: {{ edgeType: "else" }}, sourceHandle: "else" }},
] }} }};
const out: Record<string, unknown> = {{}};
for (const [k, input] of Object.entries({{ good: {{ age: 34, max: 120 }}, bad: {{ age: 0, max: 120 }} }})) {{
  const r = await executeWorkflow(wf, input);
  out[k] = {{ status: r.status, refused: r.refused ?? null, error: r.error ?? null }};
}}
console.log(JSON.stringify(out));
''')
    proc = subprocess.run([str(_tsx()), str(script)], cwd=_ROOT, capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-800:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["good"] == {"status": "completed", "refused": None, "error": None}
    assert out["bad"] == {"status": "failed", "refused": True,
                          "error": "Age must be between 1 and 120."}


def test_a_refusal_is_neither_retried_nor_shown_as_the_success_message():
    bus = (_TEMPLATES / "runtime" / "events" / "bus.ts").read_text()
    assert bus.count('result?.status === "failed" && !result.refused') == 2
    client = (_TEMPLATES / "app-foundation" / "src" / "sdk" / "client.tsx").read_text()
    # A failed run never reaches the success toast; a refused one shows its
    # own sentence as the error.
    assert 'result.status === "failed"' in client
    assert "if (result.refused === true) toast.error(message);" in client


def test_the_form_marks_what_the_workflow_requires_and_clears_after_a_create():
    from services.blueprint.app_sdk import emit_workflows

    doc = {"workflows": [{"id": "FLOW-001", "name": "Create Record", "inputs": [
        {"name": "fullName", "kind": "field", "type": "string", "required": True},
        {"name": "nickname", "kind": "field", "type": "string", "required": False}]}],
        "data": {"entities": []}}
    ts = emit_workflows(doc)
    assert '"FLOW-001", "Create Record", ["fullName"])' in ts
    client = (_TEMPLATES / "app-foundation" / "src" / "sdk" / "client.tsx").read_text()
    assert "const required = new Set(workflow.required ?? []);" in client
    assert client.count("required={required}") >= 5          # every control but a checkbox
    assert "if (out.ok && !redirectTo && !initial) setValues({});" in client


def test_the_shipped_root_layout_mounts_the_toaster():
    layout = (_TEMPLATES / "standalone-app" / "src" / "app" / "layout.tsx").read_text()
    assert 'import { Providers } from "./providers";' in layout
    assert "<Providers>{children}</Providers>" in layout
    providers = (_TEMPLATES / "app-foundation" / "src" / "app" / "providers.tsx").read_text()
    assert "<Toaster" in providers


def test_a_public_page_admits_a_signed_in_person_too(tmp_path):
    """h7gmi93x: every page public, the admin signed in with role `user` —
    403 on every workflow and every write, while a signed-out visitor saved."""
    from services.runtime_injector import _generate_workflow_api_route

    _generate_workflow_api_route(tmp_path)
    route = (tmp_path / "src/app/api/workflows/[id]/execute/route.ts").read_text()
    assert 'if (allowed && !allowed.includes("*") && !allowed.includes(String(user?.role ?? ""))) {' in route
    assert "!su?.id))" not in route
    data = (_TEMPLATES / "data-api-route.ts").read_text()
    assert '  if (roles.includes("*")) return false;' in data
    assert 'op === "read") return false' not in data
