"""Why Smith ran out of turns with the map, the code and the app in hand
(2026-10-17): the map named the product, not the file; the error was text,
not an address; reads fell out of the window; one file per step."""
from __future__ import annotations

import json

from services.smith import loop as loop_mod
from services.smith import places as where
from services.smith import reads, tools
from services.smith.loop import Observation


def _tree(tmp_path):
    app = tmp_path / "app" / "src"
    for folder in ("app/(dashboard)/payments/receipts", "app/(dashboard)/tools", "app/(dashboard)/tools/[id]",
                   "app/register", "app/_root", "app/api"):
        (app / folder).mkdir(parents=True, exist_ok=True)
        (app / folder / "view.tsx").write_text("export default function View() { return null }\n")
    (app / "app/(dashboard)/payments/receipts/load.ts").write_text("export async function load() {\n  const rows = await db.query('receipts');\n  return rows.map(r => r.total.toFixed(2));\n}\n")
    (app / "lib/workflows/definitions").mkdir(parents=True)
    (app / "lib/workflows/definitions/list-a-tool.json").write_text("{}")
    (app / "db/schema").mkdir(parents=True)
    (app / "db/schema/tool.ts").write_text("export const tools = pgTable('tools', {})\n")
    (app / "db/schema/_forge_events.ts").write_text("")
    (app / "schemas/tools").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    doc = {"meta": {"name": "T"}, "roles": [{"id": "r1", "name": "Admin"}],
           "requirements": [{"id": "q1", "text": "receipts"}],
           "pages": [{"id": "PAGE-001", "name": "Receipts", "route": "/payments/receipts", "roles": ["r1"]},
                     {"id": "PAGE-002", "name": "Tools", "route": "/tools", "roles": ["r1"]},
                     {"id": "PAGE-003", "name": "Tool", "route": "/tools/[id]", "roles": ["r1"]},
                     {"id": "PAGE-009", "name": "Nowhere", "route": "/nowhere", "roles": ["r1"]}],
           "workflows": [{"id": "FLOW-003", "name": "List a Tool"}],
           "data": {"entities": [{"id": "ENTITY-003", "name": "Tool", "table": "tools"}]}}
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    return doc


def test_the_index_names_the_files_behind_every_screen_process_and_record_type(tmp_path):
    doc = _tree(tmp_path)
    text = where.index(tmp_path, doc, ask="the receipts are blank")
    assert text.startswith("WHERE THINGS LIVE")
    assert "- screen /payments/receipts (PAGE-001, Receipts): app/src/app/(dashboard)/payments/receipts/{view.tsx, load.ts}" in text
    assert "- screen /tools/[id] (PAGE-003, Tool): app/src/app/(dashboard)/tools/[id]/{view.tsx}" in text
    assert "/nowhere" not in text                      # no view on disk, nothing to point at
    assert "- process List a Tool (FLOW-003): app/src/lib/workflows/definitions/list-a-tool.json" in text
    assert "- record type Tool (ENTITY-003, table tools): app/src/db/schema/tool.ts; its screens' schemas: app/src/schemas/tools/" in text
    # the screen the ask names comes first
    assert text.index("/payments/receipts") < text.index("/tools (")
    assert where.index(tmp_path / "elsewhere") == ""


def test_the_opening_page_carries_the_index(tmp_path):
    _tree(tmp_path)
    from services.smith4 import context
    page = context.opening("p", str(tmp_path), "the receipts are blank")
    assert "WHERE THINGS LIVE" in page and "payments/receipts/{view.tsx, load.ts}" in page


def test_an_error_is_an_address(tmp_path):
    _tree(tmp_path)
    assert tools.is_read("open_error") and "open_error" in tools.render()
    err = "TypeError: Cannot read properties of undefined (reading 'toFixed')\n    at load (./src/app/(dashboard)/payments/receipts/load.ts:3:30)"
    out = reads.run("open_error", {"error": err}, output_dir=str(tmp_path), doc={})
    assert out.startswith("The error names app/src/app/(dashboard)/payments/receipts/load.ts at line 3:")
    assert "r.total.toFixed(2)" in out


def test_a_database_message_names_the_table_and_its_schema(tmp_path):
    _tree(tmp_path)
    out = reads.run("open_error", {"error": 'error: relation "tools" does not exist'}, output_dir=str(tmp_path), doc={})
    assert "The database says `tools` does not exist" in out and "app/src/db/schema/tool.ts" in out
    assert "sync_app" in out


def test_an_error_with_no_file_searches_for_what_it_quotes(tmp_path):
    _tree(tmp_path)
    out = reads.run("open_error", {"error": "Unhandled: `toFixed` is not a function"}, output_dir=str(tmp_path), doc={})
    assert out.startswith("The error names no file. Searching the code for `toFixed`")
    assert "load.ts" in out
    assert "needs the error text" in reads.run("open_error", {}, output_dir=str(tmp_path), doc={})


def test_several_files_are_read_in_one_step(tmp_path):
    _tree(tmp_path)
    out = reads.run("read_file", {"paths": ["app/src/app/(dashboard)/payments/receipts/view.tsx",
                                            "app/src/app/(dashboard)/payments/receipts/load.ts",
                                            "app/src/nope.ts"]}, output_dir=str(tmp_path), doc={})
    assert "view.tsx — 1 lines" in out and "load.ts — 4 lines" in out and "There is no file at `app/src/nope.ts`" in out


def test_what_fell_out_of_the_window_is_kept_as_what_i_know():
    obs = [Observation(tool="read_file", args={"path": f"app/src/f{i}.ts"}, status="read", said="code") for i in range(10)]
    obs += [Observation(tool="open_page", args={"route": "/orders", "as": "Admin"}, status="read",
                        said="HTTP 500 on /orders\nbrowser error: x")]
    obs += [Observation(tool="write_page_code", args={"page": "orders"}, status="resolved", said="Rewrote /orders",
                        touched=["a.tsx"])]
    obs += [Observation(tool="grep", args={"pattern": f"p{i}"}, status="read", said="…") for i in range(14)]
    text = loop_mod._render(obs)
    assert text.startswith("WHAT I KNOW SO FAR")
    assert "- read: read_file app/src/f0.ts; read_file app/src/f1.ts" in text
    assert "- tried open_page /orders: HTTP 500 on /orders" in text
    assert "- changed (write_page_code orders): Rewrote /orders" in text
    assert "THE LAST STEPS:" in text
    # a short turn shows its steps whole, with no digest
    assert not loop_mod._render(obs[:5]).startswith("WHAT I KNOW")
