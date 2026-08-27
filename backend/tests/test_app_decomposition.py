"""Deterministic app-scale estimation + decomposition threshold (spec B2)."""

import pytest

from services.app_decomposition import estimate_app_scale, should_decompose


def test_small_app_not_large_and_not_decomposed():
    prompt = "A simple todo app with tasks, projects and users."
    scale = estimate_app_scale(prompt)
    assert scale["entities"] < 20
    assert scale["large"] is False
    assert should_decompose(prompt) is False


def test_explicit_module_count_is_large_and_decomposed():
    prompt = "Build an enterprise ERP with 40 modules covering the whole company."
    scale = estimate_app_scale(prompt)
    assert scale["entities"] >= 40
    assert scale["large"] is True
    assert should_decompose(prompt) is True


def test_long_entity_list_triggers_decompose():
    entities = ", ".join(f"Entity{i}" for i in range(30))
    prompt = f"Build a platform managing {entities}."
    assert estimate_app_scale(prompt)["entities"] >= 25
    assert should_decompose(prompt) is True


def test_threshold_env_override(monkeypatch):
    prompt = "App managing customers, orders, invoices, products, suppliers."
    # 5 entities: not large at default 20 ...
    assert should_decompose(prompt) is False
    # ... but large once the threshold drops to 4.
    monkeypatch.setenv("FORGE_DECOMPOSE_THRESHOLD", "4")
    assert should_decompose(prompt) is True
    assert estimate_app_scale(prompt)["large"] is True


def test_explicit_threshold_arg_overrides_env(monkeypatch):
    prompt = "App managing customers, orders, invoices, products, suppliers."
    monkeypatch.setenv("FORGE_DECOMPOSE_THRESHOLD", "100")
    assert should_decompose(prompt, threshold=3) is True


def test_skeleton_entity_count_wins():
    skeleton = {"data_models": [{"name": f"E{i}"} for i in range(25)]}
    assert estimate_app_scale("tiny brief", skeleton)["entities"] == 25
    assert should_decompose("tiny brief", skeleton=skeleton) is True


def test_skeleton_entities_dict_shape():
    skeleton = {"entities": {f"E{i}": {} for i in range(25)}, "pages": [1, 2, 3]}
    scale = estimate_app_scale("x", skeleton)
    assert scale["entities"] == 25
    assert scale["pages"] == 3
    assert scale["large"] is True


def test_none_and_empty_are_safe():
    assert estimate_app_scale(None) == {"entities": 0, "pages": 0, "large": False}
    assert estimate_app_scale("") == {"entities": 0, "pages": 0, "large": False}
    assert should_decompose(None) is False
    assert should_decompose("", skeleton=None) is False
    # Non-str / junk inputs must not raise.
    assert should_decompose(12345) is False  # type: ignore[arg-type]


def test_enterprise_hint_biases_toward_decompose(monkeypatch):
    # 15 entities is below the default 20 threshold, but an enterprise hint at
    # >=70% of threshold biases toward decomposing.
    entities = ", ".join(f"Module{i}" for i in range(15))
    prompt = f"An enterprise suite with modules: {entities}."
    assert estimate_app_scale(prompt)["large"] is False
    assert should_decompose(prompt) is True
