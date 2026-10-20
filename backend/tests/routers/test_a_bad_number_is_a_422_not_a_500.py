"""A request that fails validation is a 422 saying what failed — even when the
input it would echo back (NaN, Infinity) cannot be written as JSON. It was a
500 (found by an adversarial run against /business-rules/test, Oct 21)."""
import asyncio
import json

from fastapi.exceptions import RequestValidationError


def test_a_non_finite_number_is_a_422():
    import main
    exc = RequestValidationError([{"type": "value_error", "loc": ("body", "record"),
                                   "msg": "numbers in a sample record must be finite",
                                   "input": {"openingsCount": float("nan")}}])
    r = asyncio.run(main._validation_errors(None, exc))
    assert r.status_code == 422
    assert json.loads(r.body)["detail"][0]["msg"] == "numbers in a sample record must be finite"
