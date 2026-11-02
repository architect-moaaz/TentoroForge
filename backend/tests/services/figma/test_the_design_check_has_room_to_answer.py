"""The design check is given room for a row per requirement AND its thinking.

On the adaptive path `max_tokens` caps thinking and output together, so a node
that reasons hard over a large input can spend the budget before it writes.
`figma_coverage` writes one `{id, status, frames, reason}` row per requirement
while reasoning over every requirement x every frame — on kkb5mzo3 that was
157 x 18, and the reply stopped mid-string at 17,701 characters."""

from services.blueprint.executors import (
    DEFAULT_MAX_TOKENS,
    MAX_TOKENS_BY_NODE,
    tiered_router,
)


def test_the_check_is_not_left_on_the_default_cap():
    assert MAX_TOKENS_BY_NODE.get("figma_coverage", 0) > DEFAULT_MAX_TOKENS, (
        "a row per requirement plus the thinking does not fit in the default")


def test_the_router_actually_hands_that_cap_to_the_check():
    """The seam that matters: `figma_gate._client()` asks for this exact pair."""
    client = tiered_router().for_task("figma_coverage", "figma_intelligence")
    assert getattr(client, "max_tokens", 0) == MAX_TOKENS_BY_NODE["figma_coverage"]


def test_it_has_room_for_the_application_that_exposed_it():
    """157 requirements at a realistic row size, with thinking left over."""
    row_chars = 180                      # {id, status, frames[], reason} with a sentence of reason
    answer_tokens = (157 * row_chars) / 4
    assert MAX_TOKENS_BY_NODE["figma_coverage"] > answer_tokens * 2, (
        "the cap must cover the answer twice over, because the thinking shares it")
