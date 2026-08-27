"""next.config normalization guard — jsdom must be external, never transpiled."""
from services.next_config_guard import normalize_next_config, _AUTHORITATIVE

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
