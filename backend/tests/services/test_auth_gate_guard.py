"""The scaffold's login gate must honour authGated (public apps start at /)."""
import json

from services.auth_gate_guard import guard_auth_gate

_LAYOUT = (
    'import { redirect } from "next/navigation";\n'
    'export default async function DashboardLayout({ children }) {\n'
    '  const session = await auth();\n'
    '  if (!session) redirect("/login");\n'
    '  return <div>{children}</div>;\n'
    '}\n'
)


def _seed(tmp_path, gated: bool):
    c = tmp_path / "src" / "contracts"
    c.mkdir(parents=True, exist_ok=True)
    (c / "nav-flow.json").write_text(json.dumps({"authGated": gated, "pages": []}), encoding="utf-8")
    lay = tmp_path / "src" / "app" / "(dashboard)"
    lay.mkdir(parents=True, exist_ok=True)
    (lay / "layout.tsx").write_text(_LAYOUT, encoding="utf-8")
    return lay / "layout.tsx"


def test_public_app_removes_gate(tmp_path):
    layout = _seed(tmp_path, gated=False)
    assert guard_auth_gate(str(tmp_path)) == {"patched": 1}
    assert 'redirect("/login")' not in layout.read_text(encoding="utf-8")


def test_gated_app_keeps_gate(tmp_path):
    layout = _seed(tmp_path, gated=True)
    assert guard_auth_gate(str(tmp_path)) == {"patched": 0}
    assert 'if (!session) redirect("/login");' in layout.read_text(encoding="utf-8")


def test_idempotent(tmp_path):
    _seed(tmp_path, gated=False)
    assert guard_auth_gate(str(tmp_path))["patched"] == 1
    assert guard_auth_gate(str(tmp_path))["patched"] == 0


def test_no_navflow_is_noop(tmp_path):
    assert guard_auth_gate(str(tmp_path)) == {"patched": 0}
