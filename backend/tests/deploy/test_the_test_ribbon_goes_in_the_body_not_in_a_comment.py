"""An app whose layout predates the test version gets the ribbon in its real <body> tag, never in a comment that names it."""
from __future__ import annotations

from pathlib import Path

from services.deploy import vercel_provider as vp

LAYOUT_WITH_A_COMMENT_NAMING_BODY = """import "./globals.css";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: browser extensions inject attributes onto <html>/<body> before React hydrates; without this they
    // trip a benign hydration-mismatch warning. Scoped to these tags only.
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <body suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
"""

PLAIN_LAYOUT = """export default function RootLayout({ children }) {
  return (
    <html>
      <body className="app">{children}</body>
    </html>
  );
}
"""


def written(tmp_path: Path, text: str) -> Path:
    layout = tmp_path / "src" / "app" / "layout.tsx"
    layout.parent.mkdir(parents=True)
    layout.write_text(text, "utf-8")
    return layout


def test_a_comment_that_names_body_is_left_alone_and_the_ribbon_is_put_in_the_tag(tmp_path):
    layout = written(tmp_path, LAYOUT_WITH_A_COMMENT_NAMING_BODY)
    assert vp._ensure_test_ribbon(tmp_path) is True
    text = layout.read_text("utf-8")
    assert "onto <html>/<body> before React hydrates; without this they\n" in text, "the comment is as it was"
    assert text.index("<body suppressHydrationWarning>") < text.index("<TestRibbon />") < text.index("{children}")
    assert text.startswith('import { TestRibbon } from "@/components/TestRibbon";')


def test_a_plain_layout_gets_the_ribbon_after_its_body_tag(tmp_path):
    layout = written(tmp_path, PLAIN_LAYOUT)
    assert vp._ensure_test_ribbon(tmp_path) is True
    text = layout.read_text("utf-8")
    assert text.index('<body className="app">') < text.index("<TestRibbon />") < text.index("{children}")


def test_a_layout_that_has_the_ribbon_is_not_changed_again(tmp_path):
    layout = written(tmp_path, PLAIN_LAYOUT)
    vp._ensure_test_ribbon(tmp_path)
    once = layout.read_text("utf-8")
    assert vp._ensure_test_ribbon(tmp_path) is False
    assert layout.read_text("utf-8") == once


def test_a_layout_with_no_body_tag_is_left_alone(tmp_path):
    layout = written(tmp_path, "// the body is <body> in a comment only\nexport default function L() { return null; }\n")
    before = layout.read_text("utf-8")
    assert vp._ensure_test_ribbon(tmp_path) is False
    assert layout.read_text("utf-8") == before
