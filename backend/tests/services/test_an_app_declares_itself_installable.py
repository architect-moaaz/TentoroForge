"""The application on a phone: the product analysis writes `mobile`; the
projection writes the manifest, the icons at their declared sizes, the
shell worker and `src/lib/mobile.ts`; the frame registers the worker and
offers Install; a push channel is refused where push is off (2026-10-12)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidMobile, check_mobile
from services.blueprint.projection import _hsl_to_hex, mobile_policy, project_pwa

ROOT = Path(__file__).resolve().parents[2]
DOC = {"application": {"name": "Field Crew", "description": "Shifts and jobs for the crew"},
       "mobile": {"push": True, "orientation": "portrait"}, "designSystem": {}, "roles": [{"id": "ROLE-001", "name": "Worker"}]}


def test_the_policy_reads_the_blueprint_and_the_design():
    pol = mobile_policy(DOC)
    assert pol["installable"] and pol["push"] and pol["orientation"] == "portrait" and pol["display"] == "standalone"
    assert pol["themeColor"].startswith("#") and len(pol["themeColor"]) == 7 and pol["startUrl"] == "/"
    assert mobile_policy({"mobile": {"installable": False}})["installable"] is False
    assert _hsl_to_hex("0 0% 100%", "#000000") == "#ffffff" and _hsl_to_hex("nonsense", "#123456") == "#123456"


def test_the_projection_writes_manifest_icons_worker_and_policy(tmp_path):
    out = project_pwa(DOC, tmp_path)
    manifest = json.loads((tmp_path / "public/manifest.webmanifest").read_text())
    assert manifest["name"] == "Field Crew" and manifest["display"] == "standalone" and manifest["orientation"] == "portrait"
    assert [i["sizes"] for i in manifest["icons"]] == ["192x192", "512x512", "512x512"] and manifest["icons"][2]["purpose"] == "maskable"
    for icon in manifest["icons"]:
        raw = (tmp_path / "public" / icon["src"]).read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack(">II", raw[16:24])
        assert f"{w}x{h}" == icon["sizes"]
    assert (tmp_path / "public/icons/apple-touch-icon.png").exists()
    sw = (tmp_path / "public/sw.js").read_text()
    assert 'const BASE = "";' in sw and '"/offline"' in sw and "__SHELL__" not in sw and "forge-shell-" in sw
    policy = (tmp_path / "src/lib/mobile.ts").read_text()
    assert '"push": true' in policy and '"orientation": "portrait"' in policy
    assert "src/lib/mobile.ts" in out["files"] and "public/sw.js" in out["files"]
    project_pwa({**DOC, "mobile": {"installable": False}}, tmp_path)
    assert not (tmp_path / "public/manifest.webmanifest").exists() and not (tmp_path / "public/sw.js").exists()


def test_the_frame_registers_the_worker_offers_install_and_push():
    layout = (ROOT / "templates/app-foundation/src/app/layout.tsx").read_text()
    assert "manifest: `${BASE}/manifest.webmanifest`" in layout and 'themeColor: "__THEME_COLOR__"' in layout and "appleWebApp" in layout
    providers = (ROOT / "templates/app-foundation/src/app/providers.tsx").read_text()
    assert "<PwaRegister />" in providers
    frame = (ROOT / "templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert "<InstallButton />" in frame
    bell = (ROOT / "templates/app-foundation/src/app/(dashboard)/NotificationBell.tsx").read_text()
    assert "Turn on notifications on this device" in bell and "subscribeToPush()" in bell
    reg = (ROOT / "templates/app-foundation/src/components/PwaRegister.tsx").read_text()
    assert "navigator.serviceWorker.register(`${base}/sw.js`" in reg and "beforeinstallprompt" in reg and "Add to Home Screen" in reg
    assert (ROOT / "templates/app-foundation/src/app/offline/page.tsx").exists()
    assembly = (ROOT / "services/blueprint/assembly.py").read_text()
    assert '"__THEME_COLOR__"' in assembly
    orchestrator = (ROOT / "services/blueprint/orchestrator.py").read_text()
    assert "project_pwa(svc.doc, app_root)" in orchestrator and '("product", "mobile")' in orchestrator


def test_a_push_channel_needs_push_turned_on():
    flow = ArtifactProposal(section="workflows", natural_key="Tell the worker", body={
        "name": "Tell the worker", "steps": [{"id": "s1", "type": "action", "config": {"actionType": "send_notification", "channels": ["in_app", "push"]}}]})
    with pytest.raises(InvalidMobile) as e:
        check_mobile(AgentResult(task_id="T", agent="workflow", proposals=[flow]), {"mobile": {"push": False}})
    assert "mobile.push" in str(e.value)
    check_mobile(AgentResult(task_id="T", agent="workflow", proposals=[flow]), {"mobile": {"push": True}})
    with pytest.raises(InvalidMobile):
        check_mobile(AgentResult(task_id="T", agent="product_analysis", proposals=[
            ArtifactProposal(section="mobile", natural_key="mobile", body={"store": {"enabled": True}})]), {})
    from services.blueprint.agent_contract import AGENT_REGISTRY
    assert "mobile" in AGENT_REGISTRY["product_analysis"].writes
    from services.blueprint.executors import NODE_TASKS
    assert "`mobile`" in NODE_TASKS["application_model"] and "`channels`" in NODE_TASKS["workflow_steps"]
    runtime = (ROOT / "templates/runtime/workflows/index.ts").read_text()
    assert 'channels.includes("push")' in runtime and 'await import("@/lib/push")' in runtime


def test_the_layout_an_app_ships_links_the_manifest_and_the_theme_colour():
    """The scaffold is layered and the LAST layer's root layout is the one an
    app ships: the overlay's replaced the foundation's, which alone carried
    the manifest, and no built app could be installed (m1dck85j, 2026-10-12)."""
    from services.blueprint.assembly import PLACEHOLDER_PAGES, _template_dirs
    shipped = [d / "src/app/layout.tsx" for d in _template_dirs() if (d / "src/app/layout.tsx").is_file()][-1]
    src = shipped.read_text()
    assert "manifest: `${BASE}/manifest.webmanifest`" in src and 'themeColor: "__THEME_COLOR__"' in src and "appleWebApp" in src
    assert "src/app/layout.tsx" in PLACEHOLDER_PAGES, "the theme colour is filled in this file"
