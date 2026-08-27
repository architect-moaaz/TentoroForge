from services.shell_guardrail import validate_shell, is_renderable_shell, repair_shell


def _good():
    return {"schemaVersion": "2", "type": "Container", "id": "shell", "children": [
        {"type": "Container", "props": {"data-shell-region": "header"}, "children": [
            {"type": "Button", "id": "nav-home", "props": {"label": "Home"}},
        ]},
        {"type": "PageOutlet", "id": "page-outlet"},
    ]}


def test_good_shell_passes():
    assert validate_shell(_good()) == []
    assert is_renderable_shell(_good()) is True


def test_flags_zero_and_duplicate_page_outlet():
    no_outlet = {"type": "Container", "children": [{"type": "Button", "props": {}}]}
    assert any("PageOutlet" in i for i in validate_shell(no_outlet))
    dup = _good(); dup["children"].append({"type": "PageOutlet", "id": "page-outlet-2"})
    assert any("PageOutlet" in i for i in validate_shell(dup))


def test_flags_unregistered_type_and_missing_nav():
    bad = {"type": "Container", "children": [
        {"type": "ZorpWidget", "children": []},
        {"type": "PageOutlet", "id": "page-outlet"},
    ]}
    issues = validate_shell(bad)
    assert any("unregistered" in i.lower() for i in issues)
    assert any("nav" in i.lower() or "button" in i.lower() for i in issues)


def test_region_values_not_constrained():
    # A novel data-shell-region must NOT be flagged (editor metadata, not renderer-enforced)
    s = _good(); s["children"][0]["props"]["data-shell-region"] = "command-bar"
    assert validate_shell(s) == []


def test_repair_drops_duplicate_outlet():
    dup = _good(); dup["children"].append({"type": "PageOutlet", "id": "page-outlet-2"})
    fixed = repair_shell(dup)
    assert fixed is not None and is_renderable_shell(fixed)


def test_repair_returns_none_when_unrepairable():
    assert repair_shell({"type": "Container", "children": [{"type": "Button", "props": {}}]}) is None  # 0 outlets
