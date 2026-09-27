"""What a reviewer (and a person in the editor) sees is the app's, not the platform's.

From the look-test build on UAT (looktest0927, 2026-09-27): a reading list
reviewed full of books called "Quarterly review 1" by "Author 1", rated
"13.5 / 5"; every chart in the stock blue; every chart titled twice.
"""
import json
import subprocess
from pathlib import Path

from services.blueprint.executors import NODE_TASKS, SCHEMA_BY_NODE
from services.blueprint.projection import CHART_SLOTS, _seed_value, chart_palette, project_design_tokens
from services.blueprint.ui_engineer import SDK_GUIDE

ROOT = Path(__file__).resolve().parents[2]


def _sample_rows(entities, n=4):
    shim = ROOT / "static/jit-samples.mjs"
    out = subprocess.run(["node", "-e", f"""
      import({json.dumps(str(shim))}).then(m => {{
        const ents = {json.dumps(entities)};
        console.log(JSON.stringify([...Array({n}).keys()].map(i => m.sampleRow(ents[0], i, ents))));
      }})"""], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_a_field_declares_its_range_and_examples_and_the_author_is_asked():
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    text = json.dumps(schema)
    assert '"min"' in text and '"max"' in text and '"examples"' in text
    fields = SCHEMA_BY_NODE["entity_fields"]["properties"]["entities"]["items"]["properties"]["fields"]["items"]["properties"]
    assert {"min", "max", "examples"} <= set(fields)
    task = NODE_TASKS["entity_fields"]
    assert "A NUMBER WITH A FIXED RANGE SAYS SO" in task and "`examples`" in task


def test_sample_rows_keep_the_range_and_use_the_examples():
    book = {"name": "Book", "fields": [{"name": "id", "type": "uuid"},
                                       {"name": "title", "type": "string", "examples": ["Middlemarch", "Beloved"]},
                                       {"name": "author", "type": "string"},
                                       {"name": "rating", "type": "integer", "min": 1, "max": 5}]}
    rows = _sample_rows([book], 6)
    assert [r["title"] for r in rows[:2]] == ["Middlemarch", "Beloved"]
    assert all(1 <= r["rating"] <= 5 for r in rows)
    assert all(not r["author"].startswith("Author ") for r in rows), "a person-named field reads as a person"


def test_without_examples_a_thing_is_named_as_itself_not_as_office_words():
    note = {"name": "Book", "fields": [{"name": "id", "type": "uuid"}, {"name": "title", "type": "string"},
                                       {"name": "stars", "type": "integer"}]}
    rows = _sample_rows([note], 4)
    assert [r["title"] for r in rows] == ["Book 1", "Book 2", "Book 3", "Book 4"]
    assert all(1 <= r["stars"] <= 5 for r in rows), "a rating with no declared range still keeps to 1–5"


def test_the_demo_seed_keeps_the_range_and_uses_the_examples():
    rating = {"name": "rating", "type": "integer", "min": 1, "max": 5}
    assert all(1 <= _seed_value(rating, "Book", r) <= 5 for r in range(1, 13))
    assert _seed_value({"name": "title", "type": "string", "examples": ["Middlemarch", "Beloved"]}, "Book", 2) == "Beloved"


def test_charts_are_drawn_in_the_designs_colours(tmp_path):
    a = chart_palette({"primary": "#9C5A24", "accent": "#2F6F5E"})
    b = chart_palette({"primary": "#2D6A93", "accent": "#1F7A66"})
    assert len(a) == CHART_SLOTS and len(set(a)) == CHART_SLOTS, "six distinct series colours"
    assert a[0] == "27 63% 38%", "the primary leads"
    assert a != b, "two designs, two chart palettes"
    assert chart_palette({}) == []
    doc = {"designSystem": {"colors": {"primary": "#9C5A24", "accent": "#2F6F5E"}}}
    project_design_tokens(doc, tmp_path)
    css = (tmp_path / "src/app/tokens.css").read_text()
    assert all(f"--chart-{i}: " in css for i in range(1, CHART_SLOTS + 1))


def test_a_chart_is_named_once():
    view = (ROOT / "templates/app-foundation/src/sdk/widget-view.tsx").read_text()
    assert "title?: boolean;" in view and "title = true" in view and "sr-only" in view
    assert "title?={false}" in SDK_GUIDE and "Say a chart's name ONCE" in SDK_GUIDE


#: JSON-schema keywords the model API's structured output refuses. One
#: `maxItems` on the new `examples` array failed every build at data_model
#: (UAT, 2026-09-27 04:38) — the model never answered, the request was
#: refused. Bounds belong in the contract and the prompt, not the reply schema.
UNSUPPORTED = {"maxItems", "minItems", "maxLength", "minLength", "pattern", "maximum", "minimum",
               "exclusiveMaximum", "exclusiveMinimum", "uniqueItems", "multipleOf"}


def test_no_reply_schema_carries_a_keyword_the_api_refuses():
    from services.blueprint.executors import PROPOSAL_SCHEMA
    hits: list[str] = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in UNSUPPORTED and not path.endswith("properties"):
                    hits.append(f"{path}.{k}")
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    for node, schema in {**SCHEMA_BY_NODE, "proposal": PROPOSAL_SCHEMA}.items():
        walk(schema, node)
    assert hits == [], hits
