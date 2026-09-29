"""SnapIT (2026-09-29): "barcode scanner should scan the barcode from the
camera and so is the snap product".

The snap page drew a dashed box captioned "No image captured yet", its "Take
photo" opened a file picker and its barcode tab was a box to type digits into.
The app had no camera to call, so the page author drew one. The SDK now has
the camera (`@/sdk/camera`), and a page that imports it gets its packages.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint import ui_engineer
from services.blueprint.ui_engineer import SDK_GUIDE, ensure_sdk_packages

SDK = Path(ui_engineer.__file__).resolve().parents[2] / "templates/app-foundation/src/sdk"


def test_the_sdk_has_a_live_camera_and_a_barcode_reader():
    camera = (SDK / "camera.tsx").read_text()
    assert "export function CameraCapture(" in camera and "export function BarcodeScanner(" in camera
    assert "getUserMedia" in camera and "getTracks().forEach((t) => t.stop())" in camera
    assert "BarcodeDetector" in camera and 'import("@zxing/browser")' in camera


def test_only_a_page_that_uses_the_camera_pulls_it_in():
    # Every page imports @/sdk/client; an app without the barcode package must still build.
    assert "./camera" not in (SDK / "client.tsx").read_text()
    deps = json.loads((SDK.parents[1] / "package.json").read_text())["dependencies"]
    assert {"@zxing/browser", "@zxing/library"} <= set(deps)


def test_the_page_author_is_told_to_use_it():
    assert "// ---- @/sdk/camera" in SDK_GUIDE
    assert "<CameraCapture onCapture=" in SDK_GUIDE and "<BarcodeScanner onScan=" in SDK_GUIDE
    assert "never a placeholder frame standing in for a" in SDK_GUIDE


def _app(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text(json.dumps({"name": "app", "dependencies": {"next": "^15.1.0"}}))
    return tmp_path


def test_a_page_importing_the_camera_lists_its_packages(tmp_path):
    app = _app(tmp_path)
    view = '"use client";\nimport { BarcodeScanner } from "@/sdk/camera";\n'
    assert ensure_sdk_packages(app, view) == ["@zxing/browser", "@zxing/library"]
    deps = json.loads((app / "package.json").read_text())["dependencies"]
    assert deps["@zxing/browser"] and deps["@zxing/library"] and deps["next"] == "^15.1.0"
    assert ensure_sdk_packages(app, view) == []  # once


def test_a_page_without_the_camera_changes_nothing(tmp_path):
    app = _app(tmp_path)
    before = (app / "package.json").read_text()
    assert ensure_sdk_packages(app, '"use client";\nimport { useWorkflow } from "@/sdk/client";\n') == []
    assert (app / "package.json").read_text() == before


def test_packages_are_copied_in_never_installed_over_the_tree(tmp_path, monkeypatch):
    # npm in the app reifies the whole tree; a failed run broke two local apps.
    app = _app(tmp_path)
    (app / "node_modules" / "@zxing" / "library").mkdir(parents=True)
    (app / "node_modules" / "@zxing" / "library" / "package.json").write_text('{"name": "own"}')
    calls = []

    def fake_run(cmd, cwd, **kw):
        calls.append((cmd, cwd))
        root = Path(cwd) / "node_modules"
        for name in ("@zxing/browser", "@zxing/library", "ts-custom-error"):
            (root / name).mkdir(parents=True, exist_ok=True)
            (root / name / "package.json").write_text(json.dumps({"name": name, "from": "scratch"}))

        class P:
            returncode, stderr = 0, ""
        return P()

    monkeypatch.setattr(ui_engineer.subprocess, "run", fake_run)
    ensure_sdk_packages(app, 'import { CameraCapture } from "@/sdk/camera";')
    (cmd, cwd), = calls
    assert Path(cwd) != app and cmd[:2] == ["npm", "install"] and any(c.startswith("@zxing/browser@") for c in cmd)
    mods = app / "node_modules"
    assert json.loads((mods / "@zxing/browser/package.json").read_text())["from"] == "scratch"
    assert json.loads((mods / "ts-custom-error/package.json").read_text())["from"] == "scratch"
    assert json.loads((mods / "@zxing/library/package.json").read_text()) == {"name": "own"}


def test_a_page_bar_is_told_where_the_bottom_is():
    # SnapIT's "Find matches" sat under the phone tab bar and could not be tapped.
    bar = (SDK.parents[1] / "src/app/(dashboard)/MobileTabBar.tsx").read_text()
    assert "--app-bottom-inset:calc(4rem + env(safe-area-inset-bottom))" in bar
    assert "bottom-[var(--app-bottom-inset,0px)]" in ui_engineer.DESIGN_PRINCIPLES


def test_a_runs_reply_is_a_receipt_not_the_run():
    # A camera photo rode in every step's output: a 20.8 MB reply, over Vercel's 4.5 MB.
    from services import runtime_injector
    src = Path(runtime_injector.__file__).read_text()
    assert "const { output: _vars, log: _log, ..._rest }" in src
    assert "records: _records, log: _steps" in src and "error: String(e.output.error).slice(0, 500)" in src


def test_the_page_navigates_before_the_refresh():
    client = (SDK / "client.tsx").read_text()
    assert "else setTimeout(() => router.refresh(), 0);" in client


def test_the_generated_execute_route_parses(tmp_path):
    # `...(_rest)` in a destructuring passed the text checks and broke every page's build.
    import shutil
    import subprocess
    import pytest
    from services.runtime_injector import _generate_workflow_api_route
    repo = Path(ui_engineer.__file__).resolve().parents[3]
    ts = next((p for p in (repo / "node_modules/typescript", repo / "frontend/node_modules/typescript") if p.exists()), None)
    if ts is None or not shutil.which("node"):
        pytest.skip("no TypeScript to parse with")
    _generate_workflow_api_route(tmp_path)
    route = tmp_path / "src/app/api/workflows/[id]/execute/route.ts"
    script = ("const ts=require(process.argv[1]);const src=require('fs').readFileSync(process.argv[2],'utf8');"
              "const r=ts.transpileModule(src,{reportDiagnostics:true,compilerOptions:{module:1,target:99}});"
              "for(const d of r.diagnostics)console.log(ts.flattenDiagnosticMessageText(d.messageText,' '));"
              "process.exit(r.diagnostics.length?1:0)")
    proc = subprocess.run(["node", "-e", script, str(ts), str(route)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
