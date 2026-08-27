"""Border-coherence guard: hand structural border shape/weight back to the register."""
import json

from services.surface_border_guard import harmonize_surface_borders

def _subset(result: dict, expected: dict) -> dict:
    """Project a guard's return dict down to the keys the test asserts on.

    Whole-dict equality breaks every time a guard gains a counter (e.g.
    ``asserts_logged`` from the authority demotions) even though the
    behaviour under test is unchanged. Compare only what the test means.
    """
    return {k: result.get(k) for k in expected}



def _write(tmp_path, name, schema):
    d = tmp_path / "src" / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(schema))


def test_strips_radius_and_border_from_surface_containers(tmp_path):
    _write(tmp_path, "page.json", {
        "root": {"type": "Stack", "children": [
            {"type": "MetricTile", "props": {"label": "A"}},  # register-owned, no override
            {"type": "Card", "props": {"label": "B"},
             "style": {"radius": "tokens.radius.lg",
                       "background": {"type": "solid", "value": "tokens.color.success.50"},
                       "border": "1px solid x"}},
            {"type": "Table", "style": {"radius": "tokens.radius.md"}},
        ]},
    })
    res = harmonize_surface_borders(str(tmp_path))
    assert res["stripped"] == 3  # Card.radius + Card.border + Table.radius
    assert res["nodes"] == 2 and res["files"] == 1

    schema = json.loads((tmp_path / "src" / "schemas" / "page.json").read_text())
    card = schema["root"]["children"][1]
    table = schema["root"]["children"][2]
    # radius + border gone…
    assert "radius" not in card["style"] and "border" not in card["style"]
    assert "style" not in table  # emptied style dict removed entirely
    # …but the semantic fill is preserved.
    assert card["style"]["background"]["value"] == "tokens.color.success.50"


def test_leaves_leaf_and_interactive_components_alone(tmp_path):
    _write(tmp_path, "page.json", {
        "root": {"type": "Stack", "children": [
            {"type": "Button", "style": {"radius": "tokens.radius.full"}},   # pill button — intrinsic
            {"type": "Avatar", "style": {"radius": "tokens.radius.full"}},   # round avatar — intrinsic
        ]},
    })
    res = harmonize_surface_borders(str(tmp_path))
    assert res["stripped"] == 0
    schema = json.loads((tmp_path / "src" / "schemas" / "page.json").read_text())
    assert schema["root"]["children"][0]["style"]["radius"] == "tokens.radius.full"


def test_idempotent(tmp_path):
    _write(tmp_path, "page.json", {
        "root": {"type": "Card", "style": {"radius": "tokens.radius.lg"}},
    })
    assert harmonize_surface_borders(str(tmp_path))["stripped"] == 1
    assert harmonize_surface_borders(str(tmp_path))["stripped"] == 0


def test_no_schemas_dir_is_safe(tmp_path):
    assert _subset(harmonize_surface_borders(str(tmp_path)), {"stripped": 0, "nodes": 0, "files": 0}) == {"stripped": 0, "nodes": 0, "files": 0}
