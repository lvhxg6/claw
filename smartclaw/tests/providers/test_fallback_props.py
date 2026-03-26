"""Property-based tests for FallbackChain and error classification.

# Feature: smartclaw-llm-agent-core
# Properties 5, 6, 7
"""

from __future__ import annotations

import asyncio

import hypothesis.strategies as st
from hypothesis import given, settings
from langchain_core.messages import AIMessage

from smartclaw.providers.fallback import (
    FailoverError,
    FailoverReason,
    FallbackCandidate,
    FallbackChain,
    FallbackExhaustedError,
    classify_error,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_provider_st = st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N")))  # type: ignore[arg-type]
_model_st = st.text(min_size=1, max_size=20, alphabet=st.characters(categories=("L", "N")))  # type: ignore[arg-type]
_candidate_st = st.tuples(_provider_st, _model_st).map(lambda t: FallbackCandidate(*t))


class _StatusError(Exception):
    """Fake HTTP error with a status_code attribute."""

    def __init__(self, status_code: int, message: str = "error") -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Property 5: Fallback chain execution order and attempt recording
# ---------------------------------------------------------------------------


class TestFallbackExecutionOrder:
    """Property 5: Fallback chain execution order and attempt recording.

    **Validates: Requirements 3.1, 3.3, 3.6, 3.8**

    For any non-empty list of FallbackCandidates and any failure pattern where
    the first K candidates fail with retriable errors and candidate K+1 succeeds
    (or all fail), the FallbackChain should:
    (a) try candidates in list order,
    (b) skip candidates in cooldown,
    (c) record exactly one FallbackAttempt per candidate tried or skipped,
    (d) raise FallbackExhaustedError with all attempts if all candidates fail.
    """

    @settings(max_examples=100)
    @given(
        n_candidates=st.integers(min_value=1, max_value=5),
        success_idx=st.integers(min_value=0, max_value=10),
    )
    def test_execution_order_and_attempts(
        self,
        n_candidates: int,
        success_idx: int,
    ) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 5: Fallback chain execution order and attempt recording"""
        # Use unique provider names to avoid cooldown interference between candidates
        candidates = [FallbackCandidate(f"provider_{i}", f"model_{i}") for i in range(n_candidates)]
        call_order: list[tuple[str, str]] = []

        async def run(provider: str, model: str) -> AIMessage:
            call_order.append((provider, model))
            idx = len(call_order) - 1
            if idx < success_idx:
                raise _StatusError(429)  # retriable
            return AIMessage(content="ok")

        chain = FallbackChain()

        if success_idx < n_candidates:
            # Some candidate succeeds
            result = asyncio.run(
                chain.execute(candidates, run)
            )
            # (a) Tried in order up to success_idx
            for i, (p, m) in enumerate(call_order):
                assert p == candidates[i].provider
                assert m == candidates[i].model
            # (c) One attempt per candidate tried
            assert len(result.attempts) == success_idx + 1
            # Successful attempt has no error
            assert result.attempts[-1].error is None
        else:
            # All fail
            try:
                asyncio.run(
                    chain.execute(candidates, run)
                )
                raise AssertionError("Expected FallbackExhaustedError")  # noqa: TRY301
            except FallbackExhaustedError as exc:
                # (d) All attempts recorded
                assert len(exc.attempts) == n_candidates
                # (a) Order preserved
                for i, attempt in enumerate(exc.attempts):
                    assert attempt.provider == candidates[i].provider
                    assert attempt.model == candidates[i].model


# ---------------------------------------------------------------------------
# Property 6: Non-retriable errors abort fallback immediately
# ---------------------------------------------------------------------------


class TestNonRetriableAbort:
    """Property 6: Non-retriable errors abort fallback immediately.

    **Validates: Requirements 3.2**

    For any list of FallbackCandidates where candidate at index I fails with
    a FailoverReason.FORMAT error, the FallbackChain should abort immediately
    without trying candidates at index > I.
    """

    @settings(max_examples=100)
    @given(
        n_candidates=st.integers(min_value=2, max_value=5),
        format_idx=st.data(),
    )
    def test_format_error_aborts_immediately(
        self,
        n_candidates: int,
        format_idx: st.DataObject,
    ) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 6: Non-retriable errors abort fallback immediately"""
        idx = format_idx.draw(st.integers(min_value=0, max_value=n_candidates - 1))
        # Use unique provider names to avoid cooldown interference
        candidates = [FallbackCandidate(f"provider_{i}", f"model_{i}") for i in range(n_candidates)]
        call_order: list[int] = []

        async def run(provider: str, model: str) -> AIMessage:
            call_idx = len(call_order)
            call_order.append(call_idx)
            if call_idx == idx:
                raise _StatusError(400, "Invalid format in request")
            if call_idx < idx:
                raise _StatusError(429)  # retriable, before the format error
            return AIMessage(content="ok")

        chain = FallbackChain()
        try:
            asyncio.run(
                chain.execute(candidates, run)
            )
            raise AssertionError("Expected FailoverError")  # noqa: TRY301
        except FailoverError as exc:
            assert exc.reason == FailoverReason.FORMAT
            # No candidates after idx should have been tried
            assert max(call_order) == idx


# ---------------------------------------------------------------------------
# Property 7: Error classification maps to correct FailoverReason
# ---------------------------------------------------------------------------

# Mapping of status codes to expected reasons
_STATUS_REASON_MAP: dict[int, FailoverReason] = {
    401: FailoverReason.AUTH,
    403: FailoverReason.AUTH,
    429: FailoverReason.RATE_LIMIT,
    503: FailoverReason.OVERLOADED,
    529: FailoverReason.OVERLOADED,
}


class TestErrorClassification:
    """Property 7: Error classification maps to correct FailoverReason.

    **Validates: Requirements 3.4**

    For any HTTP status code and error message pair, classify_error should
    return the correct FailoverReason.
    """

    @settings(max_examples=100)
    @given(
        status=st.sampled_from([401, 403, 429, 503, 529]),
        provider=_provider_st,
        model=_model_st,
    )
    def test_known_status_codes(self, status: int, provider: str, model: str) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 7: Error classification maps to correct FailoverReason"""
        err = _StatusError(status)
        result = classify_error(err, provider, model)
        assert result.reason == _STATUS_REASON_MAP[status]
        assert result.provider == provider
        assert result.model == model

    @settings(max_examples=100)
    @given(
        provider=_provider_st,
        model=_model_st,
    )
    def test_timeout_errors(self, provider: str, model: str) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 7: Error classification — timeout"""
        err = TimeoutError("timed out")
        result = classify_error(err, provider, model)
        assert result.reason == FailoverReason.TIMEOUT

    @settings(max_examples=100)
    @given(
        msg=st.sampled_from(["Invalid format", "malformed request", "parse error", "schema validation failed"]),
        provider=_provider_st,
        model=_model_st,
    )
    def test_format_400_errors(self, msg: str, provider: str, model: str) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 7: Error classification — format 400"""
        err = _StatusError(400, msg)
        result = classify_error(err, provider, model)
        assert result.reason == FailoverReason.FORMAT

    @settings(max_examples=100)
    @given(
        status=st.integers(min_value=100, max_value=599).filter(
            lambda s: s not in {400, 401, 403, 429, 503, 529}
        ),
        provider=_provider_st,
        model=_model_st,
    )
    def test_unknown_status_codes(self, status: int, provider: str, model: str) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 7: Error classification — unknown"""
        err = _StatusError(status, "no format indicators here")
        result = classify_error(err, provider, model)
        assert result.reason == FailoverReason.UNKNOWN

    @settings(max_examples=100)
    @given(
        msg=st.text(min_size=0, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"),
        )).filter(lambda s: not any(ind in s.lower() for ind in ("format", "invalid", "malformed", "parse", "schema", "validation"))),
        provider=_provider_st,
        model=_model_st,
    )
    def test_400_no_format_is_rate_limit(self, msg: str, provider: str, model: str) -> None:
        """# Feature: smartclaw-llm-agent-core, Property 7: Error classification — 400 without format → RATE_LIMIT"""
        err = _StatusError(400, msg)
        result = classify_error(err, provider, model)
        assert result.reason == FailoverReason.RATE_LIMIT
