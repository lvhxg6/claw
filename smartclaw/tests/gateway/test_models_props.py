# Feature: smartclaw-p2a-production-services, Property 1: Pydantic 请求校验拒绝无效输入
"""Property tests for Pydantic request validation.

**Validates: Requirements 1.5**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from smartclaw.gateway.models import ChatRequest


# ---------------------------------------------------------------------------
# Property 1: Pydantic 请求校验拒绝无效输入
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(st.just(""))
def test_empty_message_rejected(message: str) -> None:
    """Empty message string must be rejected by ChatRequest."""
    with pytest.raises(ValidationError):
        ChatRequest(message=message)


@settings(max_examples=100, deadline=None)
@given(st.integers(max_value=0))
def test_non_positive_max_iterations_rejected(max_iterations: int) -> None:
    """max_iterations <= 0 must be rejected (ge=1 constraint)."""
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", max_iterations=max_iterations)


@settings(max_examples=100, deadline=None)
@given(st.text(min_size=1))
def test_valid_message_accepted(message: str) -> None:
    """Any non-empty message must be accepted."""
    req = ChatRequest(message=message)
    assert req.message == message


@settings(max_examples=100, deadline=None)
@given(st.integers(min_value=1, max_value=1000))
def test_positive_max_iterations_accepted(max_iterations: int) -> None:
    """max_iterations >= 1 must be accepted."""
    req = ChatRequest(message="hello", max_iterations=max_iterations)
    assert req.max_iterations == max_iterations


@settings(max_examples=100, deadline=None)
@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=0))
def test_missing_message_field_rejected(_: str) -> None:
    """Missing message field must raise ValidationError."""
    with pytest.raises((ValidationError, TypeError)):
        ChatRequest()  # type: ignore[call-arg]
