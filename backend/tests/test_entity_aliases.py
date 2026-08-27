"""Registry-driven entity aliases: data-init/route register each entity under
every registry-declared form, so the runtime resolver stops guessing.

The bug these guard against: a snake_case schema export (``recruitment_drives``)
was unreachable from a Pascal/camel query (``RecruitmentDrive``), and the runtime's
heuristic pluraliser can never bridge an IRREGULAR plural (``Person``↔``people``).
The registry knows all four forms — emit them as an explicit alias set.
"""
import json
from pathlib import Path

from services.runtime_injector import (
    _build_entity_alias_map,
    _canon_key,
    _generate_data_init_module,
    _generate_entity_aliases_module,
)


def _write_registry(root: Path, entities: dict) -> None:
    (root / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "contracts" / "resource-registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8"
    )


def _write_schema(root: Path, stems: list[str]) -> None:
    sdir = root / "src" / "db" / "schema"
    sdir.mkdir(parents=True, exist_ok=True)
    for s in stems:
        (sdir / f"{s}.ts").write_text("export const x = {};\n", encoding="utf-8")


def test_alias_map_indexes_every_form_of_each_entity(tmp_path: Path):
    _write_registry(tmp_path, {
        "RecruitmentDrive": {
            "name": "RecruitmentDrive", "table": "recruitment_drives",
            "slug": "recruitment-drives", "camel": "recruitmentDrive",
        },
    })
    amap = _build_entity_alias_map(tmp_path)
    aliases = ["RecruitmentDrive", "recruitment_drives", "recruitment-drives", "recruitmentDrive"]
    # every form's canonical key resolves to the SAME alias list
    for form in aliases:
        assert amap[_canon_key(form)] == aliases


def test_alias_map_bridges_irregular_plural(tmp_path: Path):
    """The whole point: Person/people cannot be bridged by pluralisation heuristics,
    but the registry declares both — so both canonical keys map to both forms."""
    _write_registry(tmp_path, {
        "Person": {"name": "Person", "table": "people",
                   "slug": "people", "camel": "person"},
    })
    amap = _build_entity_alias_map(tmp_path)
    assert "Person" in amap[_canon_key("Person")]
    assert "people" in amap[_canon_key("Person")]
    # a query by the irregular plural also resolves to the alias set
    assert "Person" in amap[_canon_key("people")]


def test_no_registry_yields_empty_map(tmp_path: Path):
    assert _build_entity_alias_map(tmp_path) == {}


def test_emitted_module_exposes_aliases_for(tmp_path: Path):
    _write_registry(tmp_path, {
        "Candidate": {"name": "Candidate", "table": "candidates",
                      "slug": "candidates", "camel": "candidate"},
    })
    _generate_entity_aliases_module(tmp_path)
    ts = (tmp_path / "src" / "lib" / "entity-aliases.ts").read_text(encoding="utf-8")
    assert "export function aliasesFor" in ts
    assert '"candidate"' in ts and "Candidate" in ts


def test_data_init_uses_aliases_when_registry_present(tmp_path: Path):
    _write_registry(tmp_path, {
        "Candidate": {"name": "Candidate", "table": "candidates",
                      "slug": "candidates", "camel": "candidate"},
    })
    _write_schema(tmp_path, ["candidates"])
    (tmp_path / "src" / "lib").mkdir(parents=True, exist_ok=True)
    _generate_data_init_module(tmp_path)
    di = (tmp_path / "src" / "lib" / "data-init.ts").read_text(encoding="utf-8")
    assert 'import { aliasesFor } from "./entity-aliases";' in di
    assert "aliases: aliasesFor(name)" in di


def test_data_init_omits_aliases_without_registry(tmp_path: Path):
    """No registry → no import of a module we didn't emit (keeps the app compiling)."""
    _write_schema(tmp_path, ["candidates"])
    (tmp_path / "src" / "lib").mkdir(parents=True, exist_ok=True)
    _generate_data_init_module(tmp_path)
    di = (tmp_path / "src" / "lib" / "data-init.ts").read_text(encoding="utf-8")
    assert "entity-aliases" not in di
    assert "registerEntity(name, value as any, { slug: name })" in di
