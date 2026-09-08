"""next.config normalization guard — jsdom must be external, never transpiled."""
from services.next_config_guard import (
    AUTHORITATIVE_NEXT_CONFIG,
    normalize_next_config,
    _AUTHORITATIVE,
    _is_wrong,
)

_BAD = """/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  transpilePackages: [
    "@tentoroforge/engine",
    "@tentoroforge/editor",
    "@tentoroforge/library",
    "@tentoroforge/renderer",
    "@tentoroforge/schema",
    "isomorphic-dompurify",
    "jsdom",
    "parse5",
    "cssstyle",
    "@asamuzakjp/css-color"
  ],
  typescript: { ignoreBuildErrors: true },
  images: { domains: ["localhost"] },
};
"""


def test_rewrites_llm_config_with_jsdom_in_transpile(tmp_path):
    (tmp_path / "next.config.js").write_text(_BAD)
    (tmp_path / "next.config.ts").write_text("export default {}")
    res = normalize_next_config(str(tmp_path))
    assert res == {"normalized": 1, "removed_variants": 1}
    out = (tmp_path / "next.config.js").read_text()
    assert "serverExternalPackages" in out
    # jsdom + subtree no longer bundled
    for bad in ("jsdom", "cssstyle", "@asamuzakjp", "parse5"):
        assert bad not in out.split("serverExternalPackages")[0]  # not in transpile block
    assert not (tmp_path / "next.config.ts").exists()


def test_leaves_authoritative_config_untouched(tmp_path):
    (tmp_path / "next.config.js").write_text(_AUTHORITATIVE)
    res = normalize_next_config(str(tmp_path))
    assert res == {"normalized": 0, "removed_variants": 0}


def test_missing_config_is_created(tmp_path):
    res = normalize_next_config(str(tmp_path))
    assert res["normalized"] == 1
    assert "serverExternalPackages" in (tmp_path / "next.config.js").read_text()


def test_idempotent(tmp_path):
    (tmp_path / "next.config.js").write_text(_BAD)
    assert normalize_next_config(str(tmp_path))["normalized"] == 1
    assert normalize_next_config(str(tmp_path))["normalized"] == 0


# ── the config actually ships the preview basePath + all runtime-read files ──

def test_authoritative_config_carries_the_preview_basepath():
    """basePath was added to the (deleted) template next.config.ts for the
    preview proxy but never to the .js that ships — so the hosted preview never
    ran under its prefix (blank iframe + /login redirect loop). The one shipped
    config must read NEXT_BASE_PATH / NEXT_ASSET_PREFIX."""
    assert "NEXT_BASE_PATH" in AUTHORITATIVE_NEXT_CONFIG
    assert "basePath: PREVIEW_BASE_PATH" in AUTHORITATIVE_NEXT_CONFIG
    assert "assetPrefix: PREVIEW_ASSET_PREFIX" in AUTHORITATIVE_NEXT_CONFIG


def test_authoritative_config_traces_every_runtime_read_file():
    """schemas + contracts + registry.json (Server Components) AND rules/**
    (rules engine) are all fs-read at render time — every one must be in the
    serverless trace or Vercel 500s / silently drops all rules. A duplicate
    `outputFileTracingIncludes` key once dropped the first set silently, so
    assert there is exactly one and it lists them all."""
    assert AUTHORITATIVE_NEXT_CONFIG.count("outputFileTracingIncludes") == 1
    for glob in ("./src/schemas/**/*.json", "./src/contracts/**/*.json",
                 "./registry.json", "./rules/**/*", "./src/rules/**/*"):
        assert glob in AUTHORITATIVE_NEXT_CONFIG, glob


def test_a_config_without_the_basepath_wiring_is_healed():
    """An older-generation config that predates the preview basePath must be
    re-asserted on the next sweep, not left to render a blank preview."""
    stale = (
        "module.exports = {\n"
        '  serverExternalPackages: ["jsdom"],\n'
        '  outputFileTracingIncludes: { "/**/*": ["./src/schemas/**/*.json"] },\n'
        "};\n"
    )
    assert _is_wrong(stale) is True


def test_emitter_uses_the_one_authoritative_config():
    """app_emitter must import the guard's constant rather than keep its own
    copy — the two-copies drift is the whole root cause of the missing
    basePath. Guard against a re-introduced inline literal."""
    import inspect
    from services import app_emitter

    src = inspect.getsource(app_emitter)
    assert "AUTHORITATIVE_NEXT_CONFIG" in src
    # No hand-rolled next.config body left behind in the emitter.
    assert "serverExternalPackages" not in src


def test_the_shipped_config_is_valid_javascript(tmp_path):
    """A hand-written config string that doesn't parse would break every
    generated app. Parse it with node when node is present."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:  # CI without node — the other tests still lock the content
        return
    cfg = tmp_path / "next.config.js"
    cfg.write_text(AUTHORITATIVE_NEXT_CONFIG, encoding="utf-8")
    r = subprocess.run([node, "--check", str(cfg)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # Deploy case (no env): the spreads collapse, no basePath key.
    probe = ('const c=require(process.argv[1]);'
             'process.stdout.write(("basePath" in c)+"|"+c.distDir);')
    out = subprocess.run([node, "-e", probe, str(cfg)],
                         capture_output=True, text=True, env={})
    assert out.stdout == "false|.next", out.stdout
