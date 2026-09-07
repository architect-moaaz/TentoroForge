from pathlib import Path
from services.theme_tokens import complete_light_theme

_CSS = """:root {
  --background: 180 9% 98%;
  --card: 0 0% 100%;
  --primary: 180 50% 33%;
}
.dark { --border: 218 15% 22%; --foreground: 0 0% 90%; }
.x { border: 1px solid hsl(var(--border)); }
"""

def test_fills_missing_light_tokens(tmp_path):
    p = tmp_path / "src" / "app"; p.mkdir(parents=True)
    (p / "globals.css").write_text(_CSS, encoding="utf-8")
    rep = complete_light_theme(tmp_path)
    assert rep["completed"]
    root = (p / "globals.css").read_text(encoding="utf-8").split(".dark")[0]
    assert "--border:" in root and "--foreground:" in root and "--muted-foreground:" in root
    assert "--ring: 180 50% 33%" in root          # derived from --primary
    # light border must be LIGHT (high lightness), not the dark .dark value
    assert "214 18% 89%" in root

def test_noop_when_complete(tmp_path):
    p = tmp_path / "src" / "app"; p.mkdir(parents=True)
    (p / "globals.css").write_text(":root { --foreground: 0 0% 10%; --border: 0 0% 90%; }", encoding="utf-8")
    assert complete_light_theme(tmp_path)["completed"] is False
