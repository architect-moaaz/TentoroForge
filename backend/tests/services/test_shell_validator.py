from services.shell_validator import validate_shell


def _shell_with(child):
    return {"schemaVersion": "2.0", "title": "App Shell", "children": [child]}


def test_valid_shell_with_one_page_outlet():
    s = _shell_with({"type": "Stack", "children": [
        {"type": "Container", "props": {"data-shell-region": "header"}, "children": [
            {"type": "Button", "props": {"label": "Dashboard", "navigate": "/dashboard"}},
        ]},
        {"type": "PageOutlet", "id": "page-outlet"},
    ]})
    nf = {"pages": [{"route": "/dashboard"}]}
    assert validate_shell(s, nf) == []


def test_no_page_outlet():
    s = _shell_with({"type": "Stack", "children": []})
    errs = validate_shell(s)
    assert any("must contain exactly one PageOutlet" in e for e in errs)


def test_two_page_outlets():
    s = _shell_with({"type": "Stack", "children": [
        {"type": "PageOutlet"},
        {"type": "PageOutlet"},
    ]})
    errs = validate_shell(s)
    assert any("found 2" in e for e in errs)


def test_rejects_placeholder_slot():
    s = _shell_with({"type": "Stack", "children": [
        {"type": "PlaceholderSlot", "$slot": "entity-table", "entity": "User"},
        {"type": "PageOutlet"},
    ]})
    errs = validate_shell(s)
    assert any("PlaceholderSlot" in e for e in errs)


def test_button_navigate_outside_nav_flow():
    s = _shell_with({"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "Mystery", "navigate": "/nowhere"}},
        {"type": "PageOutlet"},
    ]})
    nf = {"pages": [{"route": "/dashboard"}]}
    errs = validate_shell(s, nf)
    assert any("nowhere" in e for e in errs)


def test_validator_with_no_nav_flow_skips_route_check():
    s = _shell_with({"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "X", "navigate": "/anywhere"}},
        {"type": "PageOutlet"},
    ]})
    errs = validate_shell(s)  # no nav_flow → only structural checks
    assert errs == []


def test_non_dict_input():
    errs = validate_shell([])
    assert any("must be an object" in e for e in errs)
