"""Tests for schema_import_guard.reconcile_schema_imports.

Reproduces the live BUILD break: data-init.ts / data-api route.ts glob the schema
dir BEFORE schema_dedup_guard removes plural/duplicate schema files, so they emit
`import("@/db/schema/customers")` for a file that later gets deleted → webpack
`Module not found: Can't resolve '@/db/schema/customers'`. The guard reconciles
those dynamic imports to the schema files that actually survive.
"""
import re

import pytest

from services.schema_import_guard import reconcile_schema_imports


# --- fixtures ---------------------------------------------------------------

def _schema_dir(root):
    d = root / "src" / "db" / "schema"
    d.mkdir(parents=True)
    for name in ("customer", "equipment", "user", "_forge_files", "index", "relations"):
        (d / f"{name}.ts").write_text(f"// {name}\n", encoding="utf-8")
    return d


_DATA_INIT_TEMPLATE = (
    "import {{ isInitialized, markInitialized, registerEntity }} from \"./data-engine\";\n\n"
    "let _initPromise = null;\n\n"
    "export function ensureDataEngineInitialized() {{\n"
    "  if (isInitialized()) return Promise.resolve();\n"
    "  if (_initPromise) return _initPromise;\n"
    "  _initPromise = (async () => {{\n"
    "    const modules = await Promise.allSettled([\n"
    "{imports}\n"
    "    ]);\n"
    "    for (const result of modules) {{\n"
    "      if (result.status !== \"fulfilled\") continue;\n"
    "    }}\n"
    "    markInitialized();\n"
    "  }})();\n"
    "  return _initPromise;\n"
    "}}\n"
)


def _write_data_init(root, stems, indent="      "):
    imports = "\n".join(f'{indent}import("@/db/schema/{s}"),' for s in stems)
    p = root / "src" / "lib"
    p.mkdir(parents=True, exist_ok=True)
    f = p / "data-init.ts"
    f.write_text(_DATA_INIT_TEMPLATE.format(imports=imports), encoding="utf-8")
    return f


_DATA_API_TEMPLATE = (
    "export async function GET() {{\n"
    "  const modules = await Promise.allSettled([\n"
    "{imports}\n"
    "  ]);\n"
    "  for (const result of modules) {{\n"
    "    if (result.status !== \"fulfilled\") continue;\n"
    "  }}\n"
    "}}\n"
)


def _write_data_api(root, stems, indent="    "):
    imports = "\n".join(f'{indent}import("@/db/schema/{s}"),' for s in stems)
    p = root / "src" / "app" / "api" / "data" / "[...path]"
    p.mkdir(parents=True, exist_ok=True)
    f = p / "route.ts"
    f.write_text(_DATA_API_TEMPLATE.format(imports=imports), encoding="utf-8")
    return f


def _imported_stems(text):
    return sorted(re.findall(r'import\("@/db/schema/([^"]+)"\)', text))


def _brackets_balanced(text):
    return (text.count("[") == text.count("]")
            and text.count("(") == text.count(")")
            and text.count("{") == text.count("}"))


# --- data-init ---------------------------------------------------------------

def test_data_init_prunes_stale(tmp_path):
    _schema_dir(tmp_path)
    f = _write_data_init(tmp_path, ["customer", "customers", "equipment", "notifications", "user"])

    res = reconcile_schema_imports(str(tmp_path))

    text = f.read_text(encoding="utf-8")
    # customers + notifications pruned; _forge_files is a real module but ADD mirrors
    # runtime_injector's glob, which excludes `_`-prefixed framework tables — so it is
    # NOT introduced. index/relations are never importable modules.
    assert _imported_stems(text) == ["customer", "equipment", "user"]
    assert "customers" not in _imported_stems(text)
    assert "notifications" not in text
    assert _brackets_balanced(text)
    assert res["removed"] == 2  # customers, notifications
    assert res["added"] == 0    # _forge_files NOT added (underscore-prefixed)
    assert res["files_changed"] == 1


def test_forge_import_kept_when_already_present(tmp_path):
    # PRUNE must not strip an existing `_forge_*` import when its file is real —
    # ADD skips underscore, but a legitimately-present one stays.
    _schema_dir(tmp_path)
    f = _write_data_init(tmp_path, ["customer", "_forge_files", "customers"])
    reconcile_schema_imports(str(tmp_path))
    stems = _imported_stems(f.read_text(encoding="utf-8"))
    assert "_forge_files" in stems  # kept (real, already present)
    assert "customers" not in stems  # pruned (no file)


# --- data-api route ----------------------------------------------------------

def test_data_api_route_prunes_stale(tmp_path):
    _schema_dir(tmp_path)
    f = _write_data_api(tmp_path, ["customer", "customers", "equipment", "notifications", "user"])

    reconcile_schema_imports(str(tmp_path))

    text = f.read_text(encoding="utf-8")
    assert _imported_stems(text) == ["customer", "equipment", "user"]
    assert "customers" not in _imported_stems(text)
    assert "notifications" not in text
    assert _brackets_balanced(text)


# --- idempotency -------------------------------------------------------------

def test_idempotent_second_run_byte_identical(tmp_path):
    _schema_dir(tmp_path)
    fi = _write_data_init(tmp_path, ["customer", "customers", "equipment", "notifications", "user"])
    fa = _write_data_api(tmp_path, ["customer", "customers", "equipment", "notifications", "user"])

    reconcile_schema_imports(str(tmp_path))
    init_after_first = fi.read_text(encoding="utf-8")
    api_after_first = fa.read_text(encoding="utf-8")

    res2 = reconcile_schema_imports(str(tmp_path))

    assert fi.read_text(encoding="utf-8") == init_after_first
    assert fa.read_text(encoding="utf-8") == api_after_first
    assert res2["removed"] == 0
    assert res2["added"] == 0
    assert res2["files_changed"] == 0


# --- no-ops ------------------------------------------------------------------

def test_missing_schema_dir_is_noop(tmp_path):
    # No src/db/schema at all.
    res = reconcile_schema_imports(str(tmp_path))
    assert res == {"files_changed": 0, "removed": 0, "added": 0}


def test_missing_target_files_no_raise(tmp_path):
    _schema_dir(tmp_path)  # schema dir exists but no data-init / route.ts
    res = reconcile_schema_imports(str(tmp_path))
    assert res["files_changed"] == 0
    assert res["removed"] == 0


# --- full post_generate_fixes regression ------------------------------------

def test_apply_post_generate_fixes_prunes_dead_import(tmp_path):
    """End-to-end: a plural `customers` schema file that dedup would remove, with a
    data-init that still imports it. After apply_post_generate_fixes the dead import
    must be gone (proves the guard is WIRED). Fails if the wiring is removed."""
    from services.post_generate_fixes import apply_post_generate_fixes

    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True)
    # Only `customer` survives; `customers` does NOT exist as a real schema file.
    (d / "customer.ts").write_text(
        'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
        'export const customer = pgTable("customer", { id: uuid("id").primaryKey() });\n'
    )
    _write_data_init(tmp_path, ["customer", "customers"])

    apply_post_generate_fixes(str(tmp_path))

    text = (tmp_path / "src" / "lib" / "data-init.ts").read_text(encoding="utf-8")
    assert 'import("@/db/schema/customers")' not in text
    assert 'import("@/db/schema/customer")' in text
