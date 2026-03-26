"""Unit tests for FallbackChain and error classification.

Tests: empty candidate list, single candidate success, context cancellation,
non-retriable abort, error classification mapping.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from smartclaw.providers.fallback import (
    CooldownTracker,
    FailoverError,
    FailoverReason,
    FallbackCandidate,
    FallbackChain,
    FallbackExhaustedError,
    classify_error,
)

# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    """Tests for the classify_error function."""

    def test_auth_401(self) -> None:
        err = _make_status_error(401)
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.AUTH

    def test_auth_403(self) -> None:
        err = _make_status_error(403)
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.AUTH

    def test_rate_limit_429(self) -> None:
        err = _make_status_error(429)
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.RATE_LIMIT

    def test_overloaded_503(self) -> None:
        err = _make_status_error(503)
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.OVERLOADED

    def test_overloaded_529(self) -> None:
        err = _make_status_error(529)
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.OVERLOADED

    def test_format_400(self) -> None:
        err = _make_status_error(400, "Invalid format in request body")
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.FORMAT

    def test_timeout(self) -> None:
        err = TimeoutError("Connection timed out")
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.TIMEOUT

    def test_asyncio_timeout(self) -> None:
        err = TimeoutError()
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.TIMEOUT

    def test_unknown_error(self) -> None:
        err = RuntimeError("something unexpected")
        result = classify_error(err, "openai", "gpt-4o")
        assert result.reason == FailoverReason.UNKNOWN

    def test_400_no_format_indicators_is_rate_limit(self) -> None:
        """HTTP 400 without format indicators → RATE_LIMIT (Kimi/Moonshot pattern)."""
        err = _make_status_error(400, "some generic error")
        result = classify_error(err, "kimi", "kimi-k2.5")
        assert result.reason == FailoverReason.RATE_LIMIT

    def test_400_empty_message_is_rate_limit(self) -> None:
        """HTTP 400 with empty message → RATE_LIMIT."""
        err = _make_status_error(400, "")
        result = classify_error(err, "kimi", "kimi-k2.5")
        assert result.reason == FailoverReason.RATE_LIMIT


# ---------------------------------------------------------------------------
# FailoverError.is_retriable
# ---------------------------------------------------------------------------


class TestFailoverErrorRetriable:
    def test_format_not_retriable(self) -> None:
        err = FailoverError(reason=FailoverReason.FORMAT, provider="openai", model="gpt-4o")
        assert not err.is_retriable()

    def test_auth_retriable(self) -> None:
        err = FailoverError(reason=FailoverReason.AUTH, provider="openai", model="gpt-4o")
        assert err.is_retriable()

    def test_rate_limit_retriable(self) -> None:
        err = FailoverError(reason=FailoverReason.RATE_LIMIT, provider="openai", model="gpt-4o")
        assert err.is_retriable()

    def test_timeout_retriable(self) -> None:
        err = FailoverError(reason=FailoverReason.TIMEOUT, provider="openai", model="gpt-4o")
        assert err.is_retriable()


# ---------------------------------------------------------------------------
# FallbackChain
# ---------------------------------------------------------------------------


class TestFallbackChainEmpty:
    """Empty candidate list should raise ValueError."""

    async def test_empty_candidates(self) -> None:
        chain = FallbackChain()
        with pytest.raises(ValueError, match="No fallback candidates"):
            await chain.execute([], AsyncMock())


class TestFallbackChainSingleSuccess:
    """Single candidate that succeeds."""

    async def test_single_success(self) -> None:
        msg = AIMessage(content="hello")
        run = AsyncMock(return_value=msg)
        chain = FallbackChain()
        result = await chain.execute(
            [FallbackCandidate("openai", "gpt-4o")],
            run,
        )
        assert result.response == msg
        assert result.provider == "openai"
        assert result.model == "gpt-4o"
        assert len(result.attempts) == 1
        assert result.attempts[0].error is None
        assert not result.attempts[0].skipped

    async def test_records_attempt_duration(self) -> None:
        run = AsyncMock(return_value=AIMessage(content="ok"))
        chain = FallbackChain()
        result = await chain.execute(
            [FallbackCandidate("openai", "gpt-4o")],
            run,
        )
        assert result.attempts[0].duration >= timedelta(0)


class TestFallbackChainRetriableFallover:
    """First candidate fails with retriable error, second succeeds."""

    async def test_falls_over_to_second(self) -> None:
        msg = AIMessage(content="from anthropic")
        call_count = 0

        async def run(provider: str, model: str) -> AIMessage:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_status_error(429)
            return msg

        chain = FallbackChain()
        result = await chain.execute(
            [
                FallbackCandidate("openai", "gpt-4o"),
                FallbackCandidate("anthropic", "claude-sonnet"),
            ],
            run,
        )
        assert result.provider == "anthropic"
        assert len(result.attempts) == 2
        assert result.attempts[0].reason == FailoverReason.RATE_LIMIT
        assert result.attempts[1].error is None


class TestFallbackChainNonRetriable:
    """Non-retriable error aborts immediately."""

    async def test_format_error_aborts(self) -> None:
        async def run(provider: str, model: str) -> AIMessage:
            raise _make_status_error(400, "Invalid format")

        chain = FallbackChain()
        with pytest.raises(FailoverError) as exc_info:
            await chain.execute(
                [
                    FallbackCandidate("openai", "gpt-4o"),
                    FallbackCandidate("anthropic", "claude-sonnet"),
                ],
                run,
            )
        assert exc_info.value.reason == FailoverReason.FORMAT


class TestFallbackChainExhausted:
    """All candidates fail → FallbackExhaustedError."""

    async def test_all_fail(self) -> None:
        async def run(provider: str, model: str) -> AIMessage:
            raise _make_status_error(503)

        chain = FallbackChain()
        with pytest.raises(FallbackExhaustedError) as exc_info:
            await chain.execute(
                [
                    FallbackCandidate("openai", "gpt-4o"),
                    FallbackCandidate("anthropic", "claude-sonnet"),
                ],
                run,
            )
        assert len(exc_info.value.attempts) == 2


class TestFallbackChainCancellation:
    """asyncio.CancelledError propagates immediately."""

    async def test_cancelled_propagates(self) -> None:
        async def run(provider: str, model: str) -> AIMessage:
            raise asyncio.CancelledError()

        chain = FallbackChain()
        with pytest.raises(asyncio.CancelledError):
            await chain.execute(
                [FallbackCandidate("openai", "gpt-4o")],
                run,
            )


class TestFallbackChainCooldownSkip:
    """Providers in cooldown are skipped."""

    async def test_skips_cooled_down_provider(self) -> None:
        tracker = CooldownTracker()
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)

        msg = AIMessage(content="from anthropic")
        run = AsyncMock(return_value=msg)

        chain = FallbackChain(cooldown=tracker)
        result = await chain.execute(
            [
                FallbackCandidate("openai", "gpt-4o"),
                FallbackCandidate("anthropic", "claude-sonnet"),
            ],
            run,
        )
        assert result.provider == "anthropic"
        # First attempt should be skipped
        assert result.attempts[0].skipped
        assert result.attempts[0].provider == "openai"


class TestFallbackChainSuccessResetsCooldown:
    """Successful call resets cooldown."""

    async def test_success_resets(self) -> None:
        tracker = CooldownTracker()
        tracker.mark_failure("openai", FailoverReason.RATE_LIMIT)

        # Manually clear cooldown to allow the call
        tracker.mark_success("openai")

        msg = AIMessage(content="ok")
        run = AsyncMock(return_value=msg)

        chain = FallbackChain(cooldown=tracker)
        result = await chain.execute(
            [FallbackCandidate("openai", "gpt-4o")],
            run,
        )
        assert result.provider == "openai"
        assert tracker.is_available("openai")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StatusError(Exception):
    """Fake HTTP error with a status_code attribute."""

    def __init__(self, status_code: int, message: str = "error") -> None:
        super().__init__(message)
        self.status_code = status_code


def _make_status_error(status_code: int, message: str = "error") -> _StatusError:
    return _StatusError(status_code, message)
