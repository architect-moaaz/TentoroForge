"""The server draws dates in the viewer's zone and language, and every app —
one built today or one built before — carries what does it (2026-11-18).

DITANS's pages were thrown away and drawn again by React (#418) whenever a
date written without a zone came out in UTC on the server and in the person's
own zone in the browser: 680 lines in 294 files. `lib/viewer-time.ts` makes
the viewer's zone and language the server's defaults while it draws a page;
`instrumentation.ts` installs it with Next's request store; the root layout's
`<ViewerTime />` tells the server the browser's zone. A publish carries all
three to an app built before them."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.deploy import vercel_provider as vp

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_shipped_defaults_draw_the_viewers_zone_and_language():
    test = TEMPLATES / "runtime" / "__tests__" / "a-date-is-drawn-in-the-viewers-zone.test.mts"
    out = subprocess.run(["node", str(test)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-2000:]
    assert "All viewer time-zone tests passed." in out.stdout


def test_the_server_installs_them_from_the_request_it_draws():
    instr = (TEMPLATES / "runtime" / "instrumentation.ts").read_text()
    assert "await installViewerTimeDefaults();" in instr
    # before the cron switch: an app with its tick turned off still draws dates right
    assert instr.index("await installViewerTimeDefaults();") < instr.index('process.env.FORGE_CRON_DISABLE === "1"')
    assert 'import("next/dist/server/app-render/work-unit-async-storage.external")' in instr
    assert 's.type !== "request"' in instr and '"x-vercel-ip-timezone"' in instr and '"accept-language"' in instr
    assert "Forge runtime — do not remove" in instr


def test_the_browser_tells_the_server_its_zone():
    comp = (TEMPLATES / "app-foundation" / "src" / "components" / "ViewerTime.tsx").read_text()
    assert comp.startswith('"use client"') and "forge-tz=" in comp and "resolvedOptions().timeZone" in comp
    layout = (TEMPLATES / "app-foundation" / "src" / "app" / "layout.tsx").read_text()
    assert 'import { ViewerTime } from "@/components/ViewerTime";' in layout and "<ViewerTime />" in layout


OLD_LAYOUT = """import "./globals.css";
import { TestRibbon } from "@/components/TestRibbon";

export default function RootLayout({ children }) {
  return (
    <html>
      <body>
        <TestRibbon />
        {children}
      </body>
    </html>
  );
}
"""


def test_a_publish_gives_an_older_app_all_three(tmp_path):
    layout = tmp_path / "src" / "app" / "layout.tsx"
    layout.parent.mkdir(parents=True)
    layout.write_text(OLD_LAYOUT, "utf-8")
    instr = tmp_path / "src" / "instrumentation.ts"
    instr.write_text((TEMPLATES / "instrumentation.ts").read_text(), "utf-8")  # the oldest platform copy, no mark

    vp._refresh_platform_files(tmp_path)

    text = layout.read_text()
    assert text.startswith('import { ViewerTime } from "@/components/ViewerTime";')
    assert "<TestRibbon />\n        <ViewerTime />" in text
    assert vp._ensure_viewer_time(tmp_path) is False, "a second publish changes nothing"
    assert (tmp_path / "src" / "components" / "ViewerTime.tsx").is_file()
    assert (tmp_path / "src" / "lib" / "viewer-time.ts").read_text() == (TEMPLATES / "runtime" / "viewer-time.ts").read_text()
    assert instr.read_text() == (TEMPLATES / "runtime" / "instrumentation.ts").read_text()


def test_a_layout_without_the_ribbon_gets_it_in_the_body_tag(tmp_path):
    layout = tmp_path / "src" / "app" / "layout.tsx"
    layout.parent.mkdir(parents=True)
    layout.write_text("""export default function RootLayout({ children }) {
  return (
    // a comment that names <body> is not the tag
    <html>
      <body className="app">{children}</body>
    </html>
  );
}
""", "utf-8")
    assert vp._ensure_viewer_time(tmp_path) is True
    text = layout.read_text()
    assert '<body className="app">\n        <ViewerTime />{children}' in text
    assert "<body> is not the tag" in text and text.count("<ViewerTime />") == 1


def test_an_apps_own_start_up_hook_is_left_alone(tmp_path):
    instr = tmp_path / "src" / "instrumentation.ts"
    instr.parent.mkdir(parents=True)
    own = "export async function register() { /* the app's own tracing */ }\n"
    instr.write_text(own, "utf-8")
    assert vp._refresh_instrumentation(tmp_path) is False
    assert instr.read_text() == own
