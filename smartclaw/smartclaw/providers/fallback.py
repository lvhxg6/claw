"""Fallback chain, cooldown tracker, and error classification for SmartClaw LLM providers.

Implements automatic failover between LLM providers with exponential backoff cooldowns,
error classification, and ordered candidate execution.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class FailoverReason(StrEnum):
    """Classification of LLM call failure reasons."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    FORMAT = "format"
    OVERLOADED = "overloaded"
    UNKNOWN = "unknown"


@dataclass
class FailoverError(Exception):
    """Classified LLM call error with retriability information."""

    reason: FailoverReason
    provider: str
    model: str
    status: int | None = None
    wrapped: Exception | None = None

    def is_retriable(self) -> bool:
        """Return True if the error is retriable (all reasons except FORMAT)."""
        return self.reason != FailoverReason.FORMAT



class FallbackCandidate(NamedTuple):
    """A candidate provider/model pair for the fallback chain."""

    provider: str
    model: str


@dataclass
class FallbackAttempt:
    """Record of a single fallback attempt."""

    provider: str
    model: str
    error: Exception | None = None
    reason: FailoverReason | None = None
    duration: timedelta = field(default_factory=lambda: timedelta(0))
    skipped: bool = False


@dataclass
class FallbackResult:
    """Successful result from the fallback chain."""

    response: AIMessage
    provider: str
    model: str
    attempts: list[FallbackAttempt] = field(default_factory=list)


class FallbackExhaustedError(Exception):
    """Raised when all fallback candidates have been exhausted."""

    def __init__(self, attempts: list[FallbackAttempt], message: str = "All fallback candidates exhausted") -> None:
        super().__init__(message)
        self.attempts = attempts


def _extract_status_code(error: Exception) -> int | None:
    """Extract HTTP status code from common LLM client exceptions."""
    # httpx.HTTPStatusError
    resp = getattr(error, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if sc is not None:
            return int(sc)
    # OpenAI / Anthropic SDK errors often have a status_code attribute
    sc_direct = getattr(error, "status_code", None)
    if sc_direct is not None:
        return int(sc_direct)
    # Walk the cause chain
    cause = error.__cause__
    if cause is not None and isinstance(cause, Exception):
        return _extract_status_code(cause)
    return None


def _is_timeout(error: Exception) -> bool:
    """Check if the error is a timeout-related exception."""
    timeout_types = ("TimeoutError", "ConnectTimeout", "ReadTimeout", "Timeout")
    name = type(error).__name__
    if name in timeout_types:
        return True
    if isinstance(error, TimeoutError | asyncio.TimeoutError):
        return True
    cause = error.__cause__
    if cause is not None and isinstance(cause, Exception):
        return _is_timeout(cause)
    return False


def _is_format_error(error: Exception) -> bool:
    """Check if a 400-level error is a format/invalid-request error."""
    msg = str(error).lower()
    indicators = ("format", "invalid", "malformed", "parse", "schema", "validation")
    return any(ind in msg for ind in indicators)


def classify_error(error: Exception, provider: str, model: str) -> FailoverError:
    """Classify an LLM call exception into a FailoverError with a reason.

    Mapping rules:
    - HTTP 401/403 → AUTH
    - HTTP 429 → RATE_LIMIT
    - Timeout / ConnectTimeout → TIMEOUT
    - HTTP 400 + format indicators → FORMAT
    - HTTP 503/529 → OVERLOADED
    - Others → UNKNOWN
    """
    status = _extract_status_code(error)

    if _is_timeout(error):
        return FailoverError(
            reason=FailoverReason.TIMEOUT, provider=provider, model=model, status=status, wrapped=error
        )

    if status is not None:
        if status in (401, 403):
            return FailoverError(
                reason=FailoverReason.AUTH, provider=provider, model=model, status=status, wrapped=error
            )
        if status == 429:
            return FailoverError(
                reason=FailoverReason.RATE_LIMIT, provider=provider, model=model, status=status, wrapped=error
            )
        if status == 400 and _is_format_error(error):
            return FailoverError(
                reason=FailoverReason.FORMAT, provider=provider, model=model, status=status, wrapped=error
            )
        if status in (503, 529):
            return FailoverError(
                reason=FailoverReason.OVERLOADED, provider=provider, model=model, status=status, wrapped=error
            )

    return FailoverError(reason=FailoverReason.UNKNOWN, provider=provider, model=model, status=status, wrapped=error)


# ---------------------------------------------------------------------------
# Cooldown tracker
# ---------------------------------------------------------------------------

# Billing-related failure reasons that use the longer cooldown schedule
_BILLING_REASONS = frozenset({FailoverReason.AUTH})


@dataclass
class _CooldownEntry:
    """Internal per-provider cooldown state."""

    error_count: int = 0
    failure_counts: dict[FailoverReason, int] = field(default_factory=dict)
    cooldown_end: float = 0.0  # monotonic timestamp
    last_failure: float = 0.0  # monotonic timestamp


class CooldownTracker:
    """Thread-safe per-provider cooldown tracker with exponential backoff.

    Backoff schedules (reference: PicoClaw):
    - Standard: min(1h, 1min × 5^min(n-1, 3))
      → 1 error: 1 min, 2: 5 min, 3: 25 min, 4+: 1 hour
    - Billing (AUTH): min(24h, 5h × 2^min(n-1, 10))
      → 1 error: 5h, 2: 10h, 3: 20h, 4+: 24h

    Args:
        now_func: Injectable time function for testing (returns monotonic seconds).
    """

    def __init__(self, now_func: Callable[[], float] | None = None) -> None:
        self._now = now_func or time.monotonic
        self._lock = threading.Lock()
        self._entries: dict[str, _CooldownEntry] = {}

    def mark_failure(self, provider: str, reason: FailoverReason) -> None:
        """Record a failure for *provider* and start/extend cooldown."""
        now = self._now()
        with self._lock:
            entry = self._entries.setdefault(provider, _CooldownEntry())
            entry.error_count += 1
            entry.failure_counts[reason] = entry.failure_counts.get(reason, 0) + 1
            entry.last_failure = now

            cooldown_secs = self._compute_cooldown(entry.error_count, reason)
            entry.cooldown_end = now + cooldown_secs

    def mark_success(self, provider: str) -> None:
        """Reset cooldown state for *provider* after a successful call."""
        with self._lock:
            if provider in self._entries:
                del self._entries[provider]

    def is_available(self, provider: str) -> bool:
        """Return True if *provider* is not in cooldown."""
        now = self._now()
        with self._lock:
            entry = self._entries.get(provider)
            if entry is None:
                return True
            return now >= entry.cooldown_end

    def cooldown_remaining(self, provider: str) -> timedelta:
        """Return the remaining cooldown duration for *provider*."""
        now = self._now()
        with self._lock:
            entry = self._entries.get(provider)
            if entry is None:
                return timedelta(0)
            remaining = entry.cooldown_end - now
            if remaining <= 0:
                return timedelta(0)
            return timedelta(seconds=remaining)

    @staticmethod
    def _compute_cooldown(error_count: int, reason: FailoverReason) -> float:
        """Compute cooldown duration in seconds using exponential backoff."""
        if reason in _BILLING_REASONS:
            # Billing: min(24h, 5h × 2^min(n-1, 10))
            max_secs = 24 * 3600.0  # 24 hours
            base_secs = 5 * 3600.0  # 5 hours
            exponent = min(error_count - 1, 10)
            return float(min(max_secs, base_secs * (2 ** exponent)))
        # Standard: min(1h, 1min × 5^min(n-1, 3))
        max_secs = 3600.0  # 1 hour
        base_secs = 60.0  # 1 minute
        exponent = min(error_count - 1, 3)
        return float(min(max_secs, base_secs * (5 ** exponent)))


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


class FallbackChain:
    """Model failover chain — tries candidates in priority order.

    - Providers in cooldown are skipped (recorded as skipped attempts).
    - Non-retriable errors (FORMAT) abort immediately.
    - Retriable errors advance to the next candidate.
    - A successful call resets the provider's cooldown.
    - Raises FallbackExhaustedError when all candidates fail.
    - Raises ValueError for an empty candidate list.
    """

    def __init__(self, cooldown: CooldownTracker | None = None) -> None:
        self._cooldown = cooldown or CooldownTracker()

    @property
    def cooldown(self) -> CooldownTracker:
        """Access the underlying CooldownTracker."""
        return self._cooldown

    async def execute(
        self,
        candidates: list[FallbackCandidate],
        run: Callable[[str, str], Awaitable[AIMessage]],
    ) -> FallbackResult:
        """Execute the fallback chain.

        Args:
            candidates: Ordered list of (provider, model) pairs to try.
            run: Async callable that takes (provider, model) and returns an AIMessage.

        Returns:
            FallbackResult on success.

        Raises:
            ValueError: Empty candidate list.
            FallbackExhaustedError: All candidates failed.
            FailoverError: Non-retriable error encountered (aborts immediately).
        """
        if not candidates:
            raise ValueError("No fallback candidates configured")

        attempts: list[FallbackAttempt] = []

        for candidate in candidates:
            provider, model = candidate.provider, candidate.model

            # Skip providers in cooldown
            if not self._cooldown.is_available(provider):
                attempts.append(
                    FallbackAttempt(
                        provider=provider,
                        model=model,
                        skipped=True,
                        reason=None,
                        duration=timedelta(0),
                    )
                )
                continue

            start = time.monotonic()
            try:
                response = await run(provider, model)
            except asyncio.CancelledError:
                # Context cancellation — propagate immediately
                raise
            except Exception as exc:
                duration = timedelta(seconds=time.monotonic() - start)
                classified = classify_error(exc, provider, model)

                attempts.append(
                    FallbackAttempt(
                        provider=provider,
                        model=model,
                        error=classified,
                        reason=classified.reason,
                        duration=duration,
                    )
                )

                self._cooldown.mark_failure(provider, classified.reason)

                if not classified.is_retriable():
                    # Non-retriable (FORMAT) — abort immediately
                    raise classified from exc

                # Retriable — try next candidate
                continue

            # Success
            duration = timedelta(seconds=time.monotonic() - start)
            self._cooldown.mark_success(provider)
            attempts.append(
                FallbackAttempt(
                    provider=provider,
                    model=model,
                    duration=duration,
                )
            )
            return FallbackResult(
                response=response,
                provider=provider,
                model=model,
                attempts=attempts,
            )

        raise FallbackExhaustedError(attempts=attempts)
