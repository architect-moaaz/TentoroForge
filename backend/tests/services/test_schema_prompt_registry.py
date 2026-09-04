from services.schema_prompt import _registered_components, _format_library_descriptor


def test_loads_from_registry_when_present():
    names = _registered_components()
    # Registry has 58 components; with Box/Text/Image augmentation, >= 58
    assert len(names) >= 58
    # Sanity — common components must be present
    assert "Form" in names
    assert "Input" in names
    assert "MetricTile" in names


def test_control_flow_is_taught_by_the_prompt_not_the_registry():
    """`Repeat` is not a library component and never appears in the registry.

    This file asserted `"Repeat" in _registered_components()`, which could only
    ever pass by the registry carrying something it does not carry. Repeat is
    renderer control flow, and the agent learns it from the prompt body — with
    a bind example — rather than from the component list. That is the thing
    worth protecting, so it is what gets asserted.
    """
    from services.schema_prompt import _registered_components
    assert "Repeat" not in _registered_components()

    import services.schema_prompt as sp
    from pathlib import Path as _P
    body = _P(sp.__file__).read_text()
    assert '"type": "Repeat"' in body
    assert "bind" in body


def test_library_descriptor_includes_form_inputs():
    """Regression for the original diagnosis — forms were missing from prompts."""
    descriptor = _format_library_descriptor()
    for required in ("Form", "Input", "Textarea", "Select", "Checkbox"):
        assert required in descriptor, f"missing {required} from descriptor"


def test_includes_bare_primitives():
    """Box/Text/Image aren't in the registry JSON but the renderer accepts them."""
    names = _registered_components()
    assert "Box" in names
    assert "Text" in names
    assert "Image" in names
