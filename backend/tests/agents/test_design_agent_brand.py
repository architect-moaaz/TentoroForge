"""Tests for design_agent honouring an externally-supplied brand."""
import json
import tempfile
from pathlib import Path
from agents.design_agent import save_design_spec


def test_save_design_spec_uses_brand_when_provided():
    """When the spec has a `brand` field, save_design_spec rewrites
    colorPalette + globals.css :root to the brand's derived palette."""
    with tempfile.TemporaryDirectory() as tmp:
        css_path = Path(tmp) / "src" / "app" / "globals.css"
        css_path.parent.mkdir(parents=True, exist_ok=True)
        css_path.write_text("""@tailwind base;
:root {
  --background: 0 0% 100%;
  --primary: 221 83% 53%;
}""")

        spec = {
            "register": "default",
            "brand": {
                "primary_hex": "#DC2626",
                "derived": {
                    "primary": "#DC2626",
                    "secondary": "#0EA5E9",
                    "accent": "#F97316",
                    "background": "#FEF2F2",
                    "surface": "#FFFFFF",
                    "text_primary": "#0F172A",
                    "text_secondary": "#475569",
                    "border": "#FECACA",
                    "success": "#22C55E",
                    "warning": "#F59E0B",
                    "error": "#EF4444",
                },
            },
            "colorPalette": {"background": "#FFFFFF", "primary": "#FFFFFF"},
        }
        save_design_spec(tmp, spec)
        saved = json.loads((Path(tmp) / "src" / "contracts" / "design-spec.json").read_text())
        assert saved["colorPalette"]["background"] == "#FEF2F2"
        assert saved["colorPalette"]["primary"] == "#DC2626"
        # globals.css should have updated --background
        css = css_path.read_text()
        assert "--background:" in css
        assert "--background: 0 0% 100%" not in css
