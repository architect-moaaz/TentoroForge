from services.industry_design import get_industry_design, _DEFAULT_LAYOUT


def test_coarse_domains_no_longer_all_ocean():
    themes = {d: get_industry_design(d)["theme"] for d in ["general","hr","fintech","healthcare","saas"]}
    assert themes["hr"] == "hr"
    assert themes["fintech"] == "finance"
    assert themes["healthcare"] == "healthcare"
    assert themes["saas"] == "sharp"
    # at least 3 distinct themes across the coarse domains (no longer all "ocean")
    assert len(set(themes.values())) >= 3


def test_saas_layout_is_not_the_default():
    from services.industry_design import get_industry_design, _DEFAULT_LAYOUT
    saas = get_industry_design("saas")
    assert saas["theme"] == "sharp"
    # Layout fields must differ from _DEFAULT_LAYOUT — saas now has a real Government layout
    assert saas["navigation"] != _DEFAULT_LAYOUT["navigation"] or \
           saas["density"] != _DEFAULT_LAYOUT["density"] or \
           saas["dashboard_widgets"] != _DEFAULT_LAYOUT["dashboard_widgets"]
    # Specifically: saas should use topbar nav (not sidebar like default)
    assert saas["navigation"] == "topbar"
    assert saas["density"] == "compact"
