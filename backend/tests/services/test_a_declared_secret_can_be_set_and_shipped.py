"""A secret NAME an application declares is settable on the platform,
written to the app's local env and carried by a publish — under the
synthetic provider `app:<integration>`, read from the Blueprint
(2026-10-12). It used to be refused as "unknown provider/key"."""
from __future__ import annotations

import json

from services.declared_secrets import APP_PROVIDER, declared_keys, declared_keys_for_output_dir, is_declared

DOC = {"integrations": [
    {"id": "INT-001", "name": "Xero", "status": "APPROVED", "secretRefs": ["XERO_API_KEY", "XERO_TENANT_ID"]},
    {"id": "INT-002", "name": "Old", "status": "DEPRECATED", "secretRefs": ["OLD_KEY"]},
]}


def test_every_declared_name_is_a_key_under_its_integration():
    keys = declared_keys(DOC)
    assert [(k.provider, k.key, k.kind) for k in keys] == [("app:xero", "XERO_API_KEY", "password"), ("app:xero", "XERO_TENANT_ID", "password")]
    assert is_declared("app:xero", "XERO_API_KEY", keys) and not is_declared("app:xero", "OLD_KEY", keys)
    assert not is_declared("resend", "RESEND_API_KEY", keys), "the registry's own keys are the registry's"


def test_the_names_are_read_from_the_apps_blueprint_on_disk(tmp_path):
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(DOC))
    assert [k.key for k in declared_keys_for_output_dir(tmp_path)] == ["XERO_API_KEY", "XERO_TENANT_ID"]
    assert declared_keys_for_output_dir(tmp_path / "nowhere") == []


def test_the_settings_route_and_the_env_writer_know_them():
    from routers.platform_integrations import _key_known
    keys = declared_keys(DOC)
    assert _key_known("app:xero", "XERO_API_KEY", keys) and not _key_known("app:xero", "XERO_API_KEY", [])
    assert _key_known("resend", "RESEND_API_KEY")
    from pathlib import Path
    writer = (Path(__file__).resolve().parents[2] / "services" / "env_writer.py").read_text()
    assert "declared_keys_for_output_dir(output_dir)" in writer
    assert APP_PROVIDER == "app:"
