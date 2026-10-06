"""Screens that move (2026-10-07): a map, a calendar, a command palette, a
board you drag cards across, motion. The UI agent may only import what the
app has, and an app built before these parts must not break when a page first
imports one — the kit file is filled in, the package installed then."""
import json
from pathlib import Path

from services.blueprint.assembly import SCAFFOLD_DEFAULTS
from services.blueprint.ui_engineer import SDK_PACKAGES, TECH_RULES, _kit_exports, ensure_sdk_packages

FOUNDATION = Path(__file__).resolve().parents[2] / "templates" / "app-foundation"
NEW_KIT = ("sheet", "popover", "dropdown-menu", "tooltip", "switch", "scroll-area", "calendar", "command")


def _deps():
    return json.loads((FOUNDATION / "package.json").read_text())["dependencies"]


def test_every_package_the_installer_may_add_has_a_version():
    """`ensure_sdk_packages` takes each version from the template: a package
    missing there is a KeyError on the page that needed it."""
    deps = _deps()
    missing = sorted({p for pkgs in SDK_PACKAGES.values() for p in pkgs} - set(deps))
    assert missing == []


def test_the_new_kit_parts_exist_are_offered_and_fill_an_older_app():
    exports = _kit_exports()
    for name in NEW_KIT:
        assert (FOUNDATION / "src/components/ui" / f"{name}.tsx").is_file(), name
        assert f'"@/components/ui/{name}"' in exports, name
        assert f"src/components/ui/{name}.tsx" in SCAFFOLD_DEFAULTS, name


def test_the_ui_agent_is_told_what_it_may_import():
    for word in ("@dnd-kit/core", "motion/react", '"@/sdk/map"', "MapView"):
        assert word in TECH_RULES, word


def test_the_map_never_imports_its_library_on_the_server():
    src = (FOUNDATION / "src/sdk/map.tsx").read_text()
    assert 'await import("maplibre-gl")' in src
    assert 'from "maplibre-gl"' not in src.replace('import type', ''), "a value import would run on the server"


def test_a_page_importing_a_part_gets_its_package_listed(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^19.0.0"}}))
    view = 'import { Calendar } from "@/components/ui/calendar";\nimport { MapView } from "@/sdk/map";\n'
    added = ensure_sdk_packages(tmp_path, view)            # no node_modules here: listed, not installed
    deps = json.loads((tmp_path / "package.json").read_text())["dependencies"]
    assert set(added) == {"react-day-picker", "maplibre-gl"}
    assert deps["maplibre-gl"] == _deps()["maplibre-gl"]
