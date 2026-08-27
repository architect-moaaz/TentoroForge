from services.cta_defaults import defaults_for_register, CtaHierarchy


def test_default_register_returns_filled_primary():
    result = defaults_for_register("default")
    assert result["primary"]["variant"] == "primary"
    assert result["primary"]["max_per_page"] == 1
    assert result["primary"]["min_per_page"] == 1


def test_linear_register_favors_secondary_outline():
    result = defaults_for_register("linear")
    assert result["secondary"]["variant"] == "secondary"
    assert result["primary"]["max_per_page"] == 1


def test_unknown_register_returns_default():
    result = defaults_for_register("unknown-register")
    assert result["primary"]["variant"] == "primary"
