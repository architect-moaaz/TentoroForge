"""The writer that gets the last word on tailwind.config.ts must notice the glob.

Three files produce this config: `runtime_injector`'s template, the
app-foundation template, and the standalone-app scaffold. The scaffold's copy
lands first; `runtime_injector` rewrites it only when `needs_config` is true,
and `needs_config` tested three markers — the CSS-var tokens, the renderer
glob, the type scale — that the scaffold already had. A scaffold config missing
`src/schemas/**/*.json` therefore survived every build.

The cost was measured, not guessed: a real 15-page Figma build wrote 6,519
arbitrary Tailwind classes into its page schemas and compiled CSS for none of
them, because the JIT only reads what the globs point at.

The scaffold copy is patched too, but a check here is what keeps it fixed: the
next scaffold edit that drops the line meets this writer instead of the user.
"""
import inspect

from services import runtime_injector


def test_needs_config_notices_a_missing_schemas_glob():
    src = inspect.getsource(runtime_injector)
    i = src.find("needs_config = (")
    assert i != -1, "the needs_config block moved"
    # The block's own operands contain `)` — `"hsl(var(--border))"` — so the
    # first close-paren is not the end of it. The block ends at the line that
    # is nothing but the closing paren.
    end = src.find("\n            )\n", i)
    assert end != -1, "the needs_config block has no closing line"
    block = src[i:end]
    assert '"src/schemas/**/*.json" not in existing' in block


def test_the_template_it_writes_carries_the_glob():
    """Rewriting only helps if what gets written has the line."""
    assert '"./src/schemas/**/*.json"' in runtime_injector._build_tailwind_config()


def test_the_scaffold_copy_carries_the_glob_too():
    """Belt and braces: the copy that lands first should not need rewriting."""
    from pathlib import Path
    cfg = Path(runtime_injector.__file__).parent.parent / "templates" / "standalone-app" / "tailwind.config.ts"
    assert "src/schemas/**/*.json" in cfg.read_text(encoding="utf-8")
