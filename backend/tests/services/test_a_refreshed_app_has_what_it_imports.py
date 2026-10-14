"""An app brought up to the current platform has every platform file the
current files import.

Task Board (2026-10-14) was built before `@/lib/api-path`, `@/lib/push`, the
audit trail and tenancy existed. A refresh brought its notification bell,
its frame and its data engine current — and the current ones import those
files, which the refresh copies only where the app already has them. Every
page and every API call answered "Module not found". `complete_imports`
writes what is missing, from the platform's own templates, and nothing else.
"""
from __future__ import annotations

from pathlib import Path

from services.smith.sync_app import complete_imports, refresh_engine


def _old_app(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    (app / "src" / "app" / "(dashboard)").mkdir(parents=True)
    (app / "src" / "lib").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    (app / "src" / "app" / "(dashboard)" / "NotificationBell.tsx").write_text(
        'import { apiPath } from "@/lib/api-path";\n'
        'import { pushState } from "@/components/PwaRegister";\n'
        'import { OrgSwitcher } from "./OrgSwitcher";\n')
    (app / "src" / "lib" / "data-engine.ts").write_text(
        'import { recordAudit } from "./audit";\n'
        'const t = await import("./tenancy");\n'
        'const p = await import("@/lib/push");\n'
        '// from "@/db/schema/<file>" is a comment, not an import\n')
    (app / "src" / "lib" / "mine.ts").write_text('import { x } from "@/lib/not-the-platforms";\n')
    return app


def test_what_the_current_files_import_is_written(tmp_path):
    app = _old_app(tmp_path)
    written = set(complete_imports(app))
    for rel in ("src/lib/api-path.ts", "src/components/PwaRegister.tsx", "src/lib/mobile.ts",
                "src/app/(dashboard)/OrgSwitcher.tsx", "src/lib/audit.ts", "src/lib/audit-policy.ts",
                "src/lib/tenancy.ts", "src/lib/tenancy-policy.ts", "src/lib/push.ts",
                "src/db/schema/_forge_push_subscriptions.ts"):
        assert rel in written, rel
        assert (app / rel).is_file(), rel
    # The policies say "none" until the projection writes the app's own.
    assert 'level: "none"' in (app / "src/lib/audit-policy.ts").read_text()
    assert 'kind: "none"' in (app / "src/lib/tenancy-policy.ts").read_text()


def test_nothing_the_app_has_is_replaced_and_nothing_foreign_is_invented(tmp_path):
    app = _old_app(tmp_path)
    (app / "src" / "lib" / "api-path.ts").write_text("// the app's own\nexport const apiPath = (p: string) => p;\n")
    complete_imports(app)
    assert (app / "src/lib/api-path.ts").read_text().startswith("// the app's own")
    assert not (app / "src/lib/not-the-platforms.ts").exists()
    assert not (app / "src/db/schema/<file>.ts").exists()


def test_a_second_pass_finds_nothing_to_do(tmp_path):
    app = _old_app(tmp_path)
    complete_imports(app)
    assert complete_imports(app) == []


def test_a_refresh_leaves_no_platform_import_unresolved(tmp_path):
    app = _old_app(tmp_path)
    refresh_engine(app)
    assert complete_imports(app) == [], "the refresh completes what it brings"
