from services.typography_registers import (
    list_registers, get_register, pick_register_for_domain
)


def test_list_registers_returns_all_four():
    regs = list_registers()
    ids = {r["id"] for r in regs}
    assert ids == {"modern-minimal", "editorial-luxe", "technical-mono", "consumer-playful"}


def test_get_register_returns_full_data():
    reg = get_register("modern-minimal")
    assert reg["heading_font"] == "Inter"
    assert reg["body_font"] == "Inter"


def test_pick_register_for_saas_picks_modern_minimal():
    reg = pick_register_for_domain("saas")
    assert reg["id"] == "modern-minimal"


def test_pick_register_for_fitness_picks_consumer_playful():
    reg = pick_register_for_domain("fitness")
    assert reg["id"] == "consumer-playful"


def test_pick_register_for_unknown_domain_returns_default():
    reg = pick_register_for_domain("completely-unknown")
    assert reg["id"] == "modern-minimal"
