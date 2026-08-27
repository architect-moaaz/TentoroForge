from services.schema_prompt import build_schema_prompt


def test_dashboard_prompt_includes_kpi_grid_exemplar():
    plan = {"entity": {"name": "Account", "fields": []}, "page_type": "dashboard"}
    design_spec = {"register": "default"}
    prompt = build_schema_prompt(plan, design_spec=design_spec)
    # Exemplar inlined
    assert "exemplar-dashboard-kpi-grid" in prompt
    # Container choice rule still present (proves existing exemplar pipeline isn't broken)
    assert "Container choice" in prompt or "container choice" in prompt.lower()
