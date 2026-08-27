"""Generated apps must ship a Tailwind config that maps the shadcn CSS-var tokens.
An empty `theme.extend:{}` makes `@apply border-border` in globals.css fail → every
page 500s. runtime_injector repairs missing/empty configs."""
from pathlib import Path


def _write_tw(tmp_path: Path, text: str | None):
    if text is not None:
        (tmp_path / "tailwind.config.ts").write_text(text)


def _run_tailwind_step(tmp_path: Path):
    # Exercise just the tailwind-ensuring logic by importing the constant + mirroring
    # the injector's guard (kept in lockstep with runtime_injector).
    from services.runtime_injector import _SHADCN_TAILWIND_CONFIG
    cfg = tmp_path / "tailwind.config.ts"
    needs = True
    if cfg.exists():
        needs = "hsl(var(--border))" not in cfg.read_text()
    if needs:
        cfg.write_text(_SHADCN_TAILWIND_CONFIG)
    return cfg


def test_repairs_empty_extend_config(tmp_path):
    _write_tw(tmp_path, 'const config = { theme: { extend: {} } };\nexport default config;\n')
    cfg = _run_tailwind_step(tmp_path)
    assert 'border: "hsl(var(--border))"' in cfg.read_text()


def test_creates_config_when_missing(tmp_path):
    cfg = _run_tailwind_step(tmp_path)
    assert cfg.exists() and "hsl(var(--background))" in cfg.read_text()


def test_leaves_correct_config_untouched(tmp_path):
    good = 'x border: "hsl(var(--border))" x'
    _write_tw(tmp_path, good)
    cfg = _run_tailwind_step(tmp_path)
    assert cfg.read_text() == good  # already has border token → not overwritten


def test_constant_is_self_contained(tmp_path):
    from services.runtime_injector import _SHADCN_TAILWIND_CONFIG
    # must NOT import an external token module that generated apps may lack
    assert "tailwindTokens" not in _SHADCN_TAILWIND_CONFIG
    for tok in ("border", "background", "primary", "ring", "card", "accent"):
        assert f'"hsl(var(--{tok}' in _SHADCN_TAILWIND_CONFIG


def test_existing_shadcn_config_upgraded_with_renderer_glob(tmp_path):
    """An app whose tailwind.config.ts already has the shadcn token mapping but predates
    the renderer/engine content globs must be rewritten — otherwise Tailwind never sees
    the gap-*/utility classes the renderer's Stack/Grid emit and page spacing collapses."""
    from services.runtime_injector import _fix_tailwind_config
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "globals.css").write_text(":root { --border: 0 0% 90%; }\n")
    # Pre-existing config: has the border token mapping but NO renderer glob.
    (tmp_path / "tailwind.config.ts").write_text(
        'export default { content: ["./src/**/*.tsx",'
        ' "./node_modules/@tentoroforge/library/**/*.tsx"],'
        ' theme: { extend: { colors: { border: "hsl(var(--border))" } } } };\n')
    _fix_tailwind_config(tmp_path)
    out = (tmp_path / "tailwind.config.ts").read_text()
    assert "@tentoroforge/renderer" in out
    assert "@tentoroforge/engine" in out
    assert "hsl(var(--border))" in out  # still has the token mapping
