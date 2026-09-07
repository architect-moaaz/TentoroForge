"""Single-execution-path guard: the workflow engine (injected runtime + its standard
/api/workflows API) is the only path for domain logic. The BusinessLogic agent must
NOT leave per-app imperative TS services or per-entity domain-action routes that
bypass the engine. The prune pass deletes both as a safety net, while preserving the
Data Engine catch-all, auth, and the standard workflow infra routes.
"""
from pathlib import Path

from services.api_route_prune import prune_entity_crud_routes
from agents.business_logic_agent import BUSINESS_LOGIC_AGENT_SYSTEM_PROMPT


def _touch(p: Path, body: str = "// stub\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _app(root: Path) -> Path:
    api = root / "src" / "app" / "api"
    # Data Engine catch-all — the single CRUD path (must survive)
    _touch(api / "data" / "[...path]" / "route.ts")
    # Standard injected workflow infra (must survive)
    _touch(api / "workflows" / "route.ts")
    _touch(api / "workflows" / "[id]" / "execute" / "route.ts")
    _touch(api / "workflows" / "event" / "[event]" / "route.ts")
    # Auth (must survive)
    _touch(api / "auth" / "[...nextauth]" / "route.ts")
    # Redundant per-entity CRUD (deleted — existing behaviour)
    _touch(api / "leave-requests" / "route.ts")
    _touch(api / "leave-requests" / "[id]" / "route.ts")
    # Per-entity domain-action routes that bypass the engine (NEW: deleted)
    _touch(
        api / "leave-requests" / "[id]" / "approve" / "route.ts",
        'import { leaveReviewWorkflowService } from "@/services/leave-review-workflow";',
    )
    _touch(api / "leave-requests" / "[id]" / "reject" / "route.ts")
    _touch(api / "cases" / "[id]" / "advance" / "route.ts")
    # Imperative TS services (NEW: deleted)
    _touch(root / "src" / "services" / "leave-review-workflow.ts")
    _touch(root / "src" / "services" / "user-service.ts")
    return root


def test_deletes_services_and_action_routes_keeps_engine(tmp_path):
    root = _app(tmp_path)
    res = prune_entity_crud_routes(root)
    api = root / "src" / "app" / "api"

    # engine + infra survive
    assert (api / "data" / "[...path]" / "route.ts").exists()
    assert (api / "workflows" / "route.ts").exists()
    assert (api / "workflows" / "[id]" / "execute" / "route.ts").exists()
    assert (api / "workflows" / "event" / "[event]" / "route.ts").exists()
    assert (api / "auth" / "[...nextauth]" / "route.ts").exists()

    # per-entity CRUD gone (existing behaviour)
    assert not (api / "leave-requests" / "route.ts").exists()
    assert not (api / "leave-requests" / "[id]" / "route.ts").exists()

    # per-entity domain-action routes gone — they bypass the engine
    assert not (api / "leave-requests" / "[id]" / "approve" / "route.ts").exists()
    assert not (api / "leave-requests" / "[id]" / "reject" / "route.ts").exists()
    assert not (api / "cases" / "[id]" / "advance" / "route.ts").exists()
    assert sorted(res["deleted_actions"]) == [
        "cases/[id]/advance/route.ts",
        "leave-requests/[id]/approve/route.ts",
        "leave-requests/[id]/reject/route.ts",
    ]

    # imperative TS services gone
    assert not (root / "src" / "services" / "leave-review-workflow.ts").exists()
    assert not (root / "src" / "services" / "user-service.ts").exists()
    assert sorted(res["deleted_services"]) == [
        "leave-review-workflow.ts",
        "user-service.ts",
    ]


def test_idempotent_after_prune(tmp_path):
    root = _app(tmp_path)
    prune_entity_crud_routes(root)
    res2 = prune_entity_crud_routes(root)
    assert res2["deleted"] == []
    assert res2["deleted_actions"] == []
    assert res2["deleted_services"] == []
    # engine still present
    assert (root / "src" / "app" / "api" / "data" / "[...path]" / "route.ts").exists()


def test_no_services_dir_is_safe(tmp_path):
    # A project with no src/services and no entity routes must not error.
    api = tmp_path / "src" / "app" / "api"
    _touch(api / "data" / "[...path]" / "route.ts")
    res = prune_entity_crud_routes(tmp_path)
    assert res["deleted_services"] == []
    assert res["deleted_actions"] == []


def test_reserved_runtime_infra_routes_are_never_deleted(tmp_path):
    """Regression: runtime_injector._inject_file_storage writes these routes
    AFTER the pipeline emits per-entity CRUD; the prune pass runs later and
    must NOT sweep them. Before this guard, `files/upload/route.ts`
    matched `_is_domain_action_route` (`<entity>/<action>/route.ts`) and
    was silently deleted, leaving the FileUpload component POSTing to a
    404. Same problem for notifications/documents/export.
    """
    api = tmp_path / "src" / "app" / "api"
    # The engine catch-all must be present so prune has something to keep.
    _touch(api / "data" / "[...path]" / "route.ts")
    # Every route runtime_injector actually emits under src/app/api/.
    _touch(api / "files" / "upload" / "route.ts")          # 3-part; would match domain-action
    _touch(api / "files" / "[id]" / "route.ts")            # matches _CRUD_TAILS ([id], route.ts)
    _touch(api / "notifications" / "route.ts")             # matches _CRUD_TAILS (route.ts)
    _touch(api / "cron" / "tick" / "route.ts")             # cron was already reserved
    _touch(api / "documents" / "pdf" / "route.ts")         # 3-part; would match domain-action
    _touch(api / "export" / "[entity]" / "route.ts")       # 3-part with dynamic; would match domain-action

    res = prune_entity_crud_routes(tmp_path)

    # ALL of these must survive. Any deletion is a regression that breaks
    # FileUpload / send_notification workflow actions / PDF export / bulk
    # export in every generated app.
    assert (api / "files" / "upload" / "route.ts").exists(), "files/upload wiped — /api/files/upload will 404"
    assert (api / "files" / "[id]" / "route.ts").exists(), "files/[id] wiped — file downloads will 404"
    assert (api / "notifications" / "route.ts").exists(), "notifications route wiped — send_notification handlers 404"
    assert (api / "cron" / "tick" / "route.ts").exists()
    assert (api / "documents" / "pdf" / "route.ts").exists(), "documents/pdf wiped — PDF generation 404s"
    assert (api / "export" / "[entity]" / "route.ts").exists(), "export/[entity] wiped — bulk export 404s"

    # And prune shouldn't report deleting them.
    for path in res.get("deleted", []) + res.get("deleted_actions", []):
        assert not path.startswith(("files/", "notifications/", "documents/",
                                     "export/", "cron/")), (
            f"prune claimed to delete a reserved infra route: {path}"
        )


def test_prune_reads_injection_manifest_as_allowlist(tmp_path):
    """Manifest-driven prune (S4-T2): when
    contracts/runtime-injection-manifest.json is present, EVERY path in it
    is treated as infra and kept — no pattern-matching, no hand-maintained
    duplicate of the injector's route list. This kills the class of bug
    where a NEW infra route (say `/api/audit/log/route.ts`) added later
    would be silently deleted because someone forgot to update _RESERVED."""
    import json as _json
    api = tmp_path / "src" / "app" / "api"
    _touch(api / "data" / "[...path]" / "route.ts")

    # A hypothetical NEW infra root the current _RESERVED set has NEVER
    # heard of. If prune only trusts _RESERVED, this would be classified
    # as `<entity>/<action>/route.ts` and deleted.
    _touch(api / "audit" / "log" / "route.ts")
    # And a genuinely-per-entity domain action so we know the pattern
    # matcher is still active for things NOT in the manifest.
    _touch(api / "invoices" / "[id]" / "approve" / "route.ts")

    # Write the manifest exactly as runtime_injector.inject_runtime does.
    manifest = tmp_path / "contracts" / "runtime-injection-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(_json.dumps({
        "version": 1,
        "paths": [
            "src/app/api/audit/log/route.ts",  # ← the NEW infra route
            # Explicitly NOT listing invoices/[id]/approve/route.ts.
        ],
    }), encoding="utf-8")

    res = prune_entity_crud_routes(tmp_path)

    # The manifest-listed route survives even though it looks like a
    # per-entity domain action (`audit/log/route.ts`).
    assert (api / "audit" / "log" / "route.ts").exists(), (
        "manifest-listed infra route was deleted — allowlist not wired"
    )
    # The non-manifest domain-action route is still swept.
    assert not (api / "invoices" / "[id]" / "approve" / "route.ts").exists()
    assert "invoices/[id]/approve/route.ts" in res.get("deleted_actions", [])


def test_prune_falls_back_when_manifest_is_missing_or_broken(tmp_path):
    """When the manifest file is missing, the LEGACY_MANIFEST_FALLBACK
    keeps the currently-known set of injected routes alive. This means an
    older tree (or a run that failed before writing the manifest) doesn't
    lose its infra routes."""
    api = tmp_path / "src" / "app" / "api"
    _touch(api / "data" / "[...path]" / "route.ts")
    # Every currently-injected route path — no manifest written on purpose.
    for rel in (
        "files/upload/route.ts",
        "files/[id]/route.ts",
        "notifications/route.ts",
        "documents/pdf/route.ts",
        "export/[entity]/route.ts",
    ):
        _touch(api / rel)

    # NOT writing contracts/runtime-injection-manifest.json — simulates an
    # older app or a failed-injection run.

    prune_entity_crud_routes(tmp_path)

    for rel in (
        "files/upload/route.ts",
        "files/[id]/route.ts",
        "notifications/route.ts",
        "documents/pdf/route.ts",
        "export/[entity]/route.ts",
    ):
        assert (api / rel).exists(), (
            f"legacy fallback lost {rel} — prune allowlist broken for pre-manifest apps"
        )


def test_prune_manifest_shape_is_stable(tmp_path):
    """Consumers (this test + real prune) depend on the manifest shape.
    Pin `{version: 1, paths: [str, ...]}` — a runtime_injector change
    that alters the schema breaks prune, so this test flags it early."""
    from services.runtime_injector import _write_injection_manifest, _INJECTION_MANIFEST_REL
    import json as _json
    _write_injection_manifest(tmp_path, [
        "src/app/api/files/upload/route.ts",
        "src/lib/pdf.ts",
    ])
    payload = _json.loads((tmp_path / _INJECTION_MANIFEST_REL).read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert isinstance(payload["paths"], list)
    # Sorted + deduped.
    assert payload["paths"] == [
        "src/app/api/files/upload/route.ts",
        "src/lib/pdf.ts",
    ]


def test_prompt_is_workflow_json_only():
    """The system prompt must forbid TS services + per-entity routes and drop the
    old 'write a service file / create approval routes' mandates."""
    p = BUSINESS_LOGIC_AGENT_SYSTEM_PROMPT
    # forbids both bypass artifacts
    assert "src/services/" in p
    assert "Do NOT create" in p
    # old mandates removed
    assert "One service file per workflow area" not in p
    assert "APPROVAL API ROUTES (CRITICAL" not in p
