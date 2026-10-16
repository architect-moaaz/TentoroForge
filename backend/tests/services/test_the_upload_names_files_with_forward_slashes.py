"""The files uploaded to Vercel are named with forward slashes, whatever the machine.

On Windows the snapshot named a file `src\db\reset-schema.ts`. Vercel keys files by `a/b`, so that was ONE file with
backslashes in its name, and the build then died on `Cannot find module '/vercel/path1/src/db/reset-schema.ts'`: the first
publish of a real app (Iron Log) failed there, after the upload and the database had both worked."""
from __future__ import annotations

from services.deploy.snapshot import build_snapshot, build_snapshot_upload


def make(tmp_path):
    for rel in ("package.json", "src/db/reset-schema.ts", "src/app/(dashboard)/page.tsx", "vendor/@tentoroforge/engine/dist/index.js"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", "utf-8")
    return tmp_path


def test_the_upload_lists_nested_files_by_their_slash_path(tmp_path):
    names = sorted(f["file"] for f in build_snapshot_upload(make(tmp_path)))
    assert names == ["package.json", "src/app/(dashboard)/page.tsx", "src/db/reset-schema.ts",
                     "vendor/@tentoroforge/engine/dist/index.js"]
    assert not any("\\" in n for n in names)


def test_the_inline_snapshot_agrees(tmp_path):
    names = sorted(f["file"] for f in build_snapshot(make(tmp_path)))
    assert "src/db/reset-schema.ts" in names and not any("\\" in n for n in names)
