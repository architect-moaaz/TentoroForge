"""`+` between a number and a number written as text is arithmetic.

A numeric (money) column comes back from the database as text ("100.00"). Zomato's Place order
added `itemTotal - discount + deliveryFee + tax`; the fee was "100.00", so the sum was joined
into "469100" + "23.45" = "46910023.45" and the customer's order cost crores (2026-11-13).
Text beside text (a phone number, a code) is still joined.
"""
from runtime.feel_lite.evaluator import evaluate_expression


def test_a_number_plus_a_money_column_read_as_text_is_added():
    assert evaluate_expression("itemTotal + deliveryFee", {"itemTotal": 469, "deliveryFee": "100.00"}) == 569


def test_the_order_of_the_two_does_not_matter():
    assert evaluate_expression("deliveryFee + itemTotal", {"itemTotal": 469, "deliveryFee": "100.00"}) == 569


def test_the_whole_total_adds_up_with_a_fee_read_as_text():
    got = evaluate_expression("itemTotal - discountAmount + deliveryFee + taxAmount",
                              {"itemTotal": 469, "discountAmount": 0, "deliveryFee": "100.00", "taxAmount": 23.45})
    assert abs(got - 592.45) < 1e-9


def test_text_beside_text_is_still_joined():
    assert evaluate_expression("a + b", {"a": "91", "b": "98"}) == "9198"


def test_a_word_beside_a_number_is_still_joined():
    assert evaluate_expression("label + n", {"label": "Table ", "n": 5}) == "Table 5"
