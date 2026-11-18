"""An AI account with no credit is not retried as if it were a rate limit."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from llms.async_client import _is_rate_limit_like, is_account_exhausted  # noqa: E402


class RateLimitError(Exception):
    pass


def test_no_credit_is_not_retried():
    exhausted = RateLimitError("Error code: 429 - {'error': {'message': 'You have no credits remaining.', "
                               "'type': 'insufficient_quota', 'code': 'credit_balance_exhausted'}}")
    assert is_account_exhausted(exhausted)
    assert _is_rate_limit_like(exhausted) is False


def test_a_real_rate_limit_is_still_retried():
    assert _is_rate_limit_like(RateLimitError("Error code: 429 - Rate limit reached for requests")) is True
