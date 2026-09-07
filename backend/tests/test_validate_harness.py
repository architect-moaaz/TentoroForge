"""Slice 1 validation harness — unit tests for the pure route/parse/summarise
layer (the Playwright crawl itself is verified against a live app)."""
from services.validate_harness import (
    routes_from_registry, parse_crawl_output, summarize)

REGISTRY = '''// Auto-generated
import { loadSchema } from "./load";
export const schemas: Record<string, () => Promise<unknown>> = {
  "/": () => import("./home.json"),
  "/reservations": () => import("./reservations.json"),
  "/reservations/[id]": () => import("./reservations/[id].json"),
};
'''

def test_routes_from_registry(tmp_path):
    p = tmp_path / "src" / "schemas"; p.mkdir(parents=True)
    (p / "registry.ts").write_text(REGISTRY, encoding="utf-8")
    assert routes_from_registry(tmp_path) == ["/", "/reservations", "/reservations/[id]"]

def test_routes_missing_registry_defaults_to_root(tmp_path):
    assert routes_from_registry(tmp_path) == ["/"]

def test_parse_crawl_output_extracts_findings():
    out = 'boot log noise\n===FINDINGS===\n{"findings":[{"type":"route_404","route":"/x"}]}\n===END===\ntrailing'
    f = parse_crawl_output(out)
    assert f == [{"type": "route_404", "route": "/x"}]

def test_parse_crawl_output_no_block():
    assert parse_crawl_output("nothing here") == []

def test_parse_crawl_output_bad_json():
    assert parse_crawl_output("===FINDINGS===\nnot json\n===END===") == []

def test_summarize_rolls_up_by_type():
    s = summarize([{"type":"route_404"},{"type":"route_404"},{"type":"dead_button"}])
    assert s["total"] == 3 and s["by_type"] == {"route_404": 2, "dead_button": 1}
    assert s["clean"] is False
    assert summarize([])["clean"] is True
