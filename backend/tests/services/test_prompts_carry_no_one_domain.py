"""The agents' instructions teach a way of thinking, not one product.

Examples written while fixing Tool Share (036farqu) — a drill, a deposit, a
terracotta accent, "Request to borrow" — would nudge every application toward
tool-sharing words and looks. What an application says, shows and is coloured
comes from its own description through the agents; the prompts stay neutral.
"""
import re

from services.blueprint.executors import NODE_TASKS
from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, SDK_GUIDE

ONE_PRODUCT = re.compile(r"\b(drill|borrow\w*|deposit|terracotta|fraunces|rental|handover|kyc|tool ?share|toolId)\b", re.I)


def test_no_prompt_is_written_in_one_products_words():
    texts = {**NODE_TASKS, "DESIGN_PRINCIPLES": DESIGN_PRINCIPLES, "SDK_GUIDE": SDK_GUIDE}
    hits = {k: sorted({m.group(0).lower() for m in ONE_PRODUCT.finditer(t)}) for k, t in texts.items()}
    assert {k: v for k, v in hits.items() if v} == {}
