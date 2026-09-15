"""The vision critic must not fault a page for what a still image cannot show.

A closed `<select>` renders only its placeholder ("—") in a screenshot; its
options appear on click. The critic once read that as MISSING CONTENT / an
unpopulated, non-functional dropdown and burned a whole re-compose round on a
page whose schema already had all four options — measured on Test Generation 2's
`/support-requests/new`. The prompt now tells it a screenshot can't judge a
select's options, and that driving the control checks them separately.
"""
from services.visual_qa_critic import _PROMPT


def test_the_prompt_tells_the_critic_a_screenshot_cannot_judge_a_dropdown():
    p = _PROMPT.lower()
    assert "dropdown" in p and "select" in p
    # it must say the options are not visible / not to be faulted from the shot
    assert "on click" in p
    assert "do not report a dropdown as empty" in p or "unpopulated" in p


def test_the_prompt_defers_select_correctness_to_the_functional_pass():
    # The screenshot does not judge options; driving the control does.
    assert "driving the control" in _PROMPT
