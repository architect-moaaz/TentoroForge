from services.schema_prompt import _registered_components, _format_library_descriptor


def test_loads_from_registry_when_present():
    names = _registered_components()
    # Registry has 58 components; with Box/Text/Image augmentation, >= 58
    assert len(names) >= 58
    # Sanity — common components must be present
    assert "Form" in names
    assert "Input" in names
    assert "MetricTile" in names
    assert "Repeat" in names
    assert "Conditional" in names


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
