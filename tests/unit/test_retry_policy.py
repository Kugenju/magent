import random

import pytest
from pydantic import BaseModel

from magent.reliability.policy import RetryPolicy, TimeoutPolicy


class S(BaseModel):
    value: int = 0


def test_retry_policy_defaults():
    p = RetryPolicy()
    assert p.max_attempts == 1
    assert p.backoff_base == 0.5
    assert p.backoff_max == 30.0
    assert p.jitter == 0.1


def test_retry_policy_validates_max_attempts():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=-3)


def test_retry_policy_validates_backoff():
    with pytest.raises(ValueError):
        RetryPolicy(backoff_base=-1.0)
    with pytest.raises(ValueError):
        RetryPolicy(backoff_max=-1.0)
    with pytest.raises(ValueError):
        RetryPolicy(backoff_base=2.0, backoff_max=1.0)


def test_retry_policy_validates_jitter():
    with pytest.raises(ValueError):
        RetryPolicy(jitter=-0.1)
    with pytest.raises(ValueError):
        RetryPolicy(jitter=1.1)


def test_should_retry_respects_max_attempts():
    p = RetryPolicy(max_attempts=3)
    assert p.should_retry(1) is True
    assert p.should_retry(2) is True
    assert p.should_retry(3) is False
    assert p.should_retry(4) is False


def test_backoff_grows_exponentially():
    p = RetryPolicy(max_attempts=5, backoff_base=0.1, backoff_max=10.0, jitter=0.0)
    rng = random.Random(0).random
    d1 = p.backoff_delay(1, rng)
    d2 = p.backoff_delay(2, rng)
    d3 = p.backoff_delay(3, rng)
    assert d1 == 0.1
    assert d2 == 0.2
    assert d3 == 0.4


def test_backoff_is_capped():
    p = RetryPolicy(max_attempts=10, backoff_base=1.0, backoff_max=3.0, jitter=0.0)
    rng = random.Random(0).random
    assert p.backoff_delay(10, rng) == 3.0
    assert p.backoff_delay(100, rng) == 3.0


def test_jitter_stays_within_bounds():
    p = RetryPolicy(max_attempts=5, backoff_base=1.0, backoff_max=10.0, jitter=1.0)
    rng = random.Random(7).random
    for attempt in range(1, 5):
        exp = p.backoff_base * (2 ** (attempt - 1))
        delay = p.backoff_delay(attempt, rng)
        assert delay >= min(p.backoff_max, exp)
        assert delay <= p.backoff_max + p.jitter


def test_timeout_policy_defaults():
    t = TimeoutPolicy()
    assert t.node_timeout is None
    with pytest.raises(ValueError):
        TimeoutPolicy(node_timeout=-1.0)
    assert TimeoutPolicy(node_timeout=0.0).node_timeout == 0.0


def test_policies_are_immutable():
    p = RetryPolicy(max_attempts=3, backoff_base=0.5)
    with pytest.raises(Exception):
        p.max_attempts = 9  # type: ignore[misc]
