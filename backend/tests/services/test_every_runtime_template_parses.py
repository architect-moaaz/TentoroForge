"""Every TypeScript file the runtime and the app foundation ship parses. A second `const now` in
the clock's tick route passed every test — none compiled it — and failed
the app's build at the very last step (60v142ju, 2026-10-12). TypeScript
transpiles each file and Node parses the result; a template that would not compile fails
here, not in a person's build."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "templates" / "runtime"
TYPESCRIPT = Path(__file__).resolve().parents[3] / "node_modules" / "typescript"
FOUNDATION = ROOT.parent / "app-foundation" / "src"
OVERLAY = ROOT.parent / "standalone-app" / "src"
FILES = sorted(p for base in (ROOT, FOUNDATION, OVERLAY) for ext in ("*.ts", "*.tsx") for p in base.rglob(ext)
               if "__tests__" not in p.parts and not p.name.endswith(".d.ts"))

SCRIPT = r"""
const fs = require("fs"), vm = require("vm");
const ts = require(process.argv[1]);
const out = {};
for (const f of JSON.parse(fs.readFileSync(0, "utf8"))) {
  try {
    // `{{landing_for}}` and kin are filled by assembly before an app compiles
    // (interpolate_edge_pages); a neutral value stands in for them here.
    const t = ts.transpileModule(fs.readFileSync(f, "utf8").replace(/\{\{[a-z_]+\}\}/g, "0"), {
      reportDiagnostics: true, fileName: f,
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX } });
    const bad = (t.diagnostics || []).map((d) => ts.flattenDiagnosticMessageText(d.messageText, " "));
    if (bad.length) { out[f] = bad.join("; "); continue; }
    new vm.SourceTextModule(t.outputText, { identifier: f });
  } catch (e) { out[f] = String(e && e.message || e); }
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None or not TYPESCRIPT.is_dir(), reason="node or typescript is not installed")
def test_every_runtime_template_parses():
    assert len(FILES) > 20
    done = subprocess.run(["node", "--experimental-vm-modules", "--no-warnings", "-e", SCRIPT, str(TYPESCRIPT)],
                          input=json.dumps([str(f) for f in FILES]), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-800:]
    broken = json.loads(done.stdout or "{}")
    assert broken == {}, "\n".join(f"{Path(k).relative_to(ROOT.parent)}: {v}" for k, v in broken.items())
