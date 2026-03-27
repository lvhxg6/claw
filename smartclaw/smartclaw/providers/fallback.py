"""Fallback chain, cooldown tracker, and error classification for SmartClaw LLM providers.

Implements automatic failover between LLM providers with exponential backoff cooldowns,
error classification, ordered candidate execution, and two-stage AuthProfile rotation.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage

    from smartclaw.providers.config import AuthProfile

logger = logging.getLogger(__name__)


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
    """A candidate provider/model pair for the fallback chain.

    When ``profile_id`` is set, the CooldownTracker uses it as the cooldown
    key so that different AuthProfiles for the same provider have independent
    cooldown state.
    """

    provider: str
    model: str
    profile_id: str | None = None


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


def _is_rate_limit_400(error: Exception) -> bool:
    """Check if a 400 error is actually a rate limit / quota exhaustion.

    Some providers (notably Kimi/Moonshot) return HTTP 400 instead of 429
    for rate limiting. We detect this by checking for rate/quota/limit
    indicators in the error message, or by treating 400 errors that are
    NOT format errors as likely rate limits.
    """
    msg = str(error).lower()
    rate_indicators = (
        "rate", "limit", "quota", "throttl", "too many", "concurren",
        "capacity", "overload", "busy", "retry", "cooldown",
    )
    return any(ind in msg for ind in rate_indicators)


def classify_error(error: Exception, provider: str, model: str) -> FailoverError:
    """Classify an LLM call exception into a FailoverError with a reason.

    Mapping rules:
    - HTTP 401/403 → AUTH
    - HTTP 429 → RATE_LIMIT
    - Timeout / ConnectTimeout → TIMEOUT
    - HTTP 400 + format indicators → FORMAT
    - HTTP 400 + rate/quota indicators → RATE_LIMIT
    - HTTP 400 (no indicators) → RATE_LIMIT (conservative: treat as transient)
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
        if status == 400:
            if _is_format_error(error):
                return FailoverError(
                    reason=FailoverReason.FORMAT, provider=provider, model=model, status=status, wrapped=error
                )
            # 400 without format indicators → treat as rate limit (Kimi/Moonshot pattern)
            return FailoverError(
                reason=FailoverReason.RATE_LIMIT, provider=provider, model=model, status=status, wrapped=error
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
    """Thread-safe cooldown tracker with exponential backoff.

    The cooldown key is determined by the candidate's ``profile_id`` when
    present, falling back to the ``provider`` name when absent.  This allows
    independent cooldown tracking per AuthProfile while remaining backward
    compatible with the original provider-level tracking.

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

    @staticmethod
    def _cooldown_key(provider: str, profile_id: str | None = None) -> str:
        """Return the cooldown key: *profile_id* when set, else *provider*."""
        return profile_id if profile_id is not None else provider

    def mark_failure(
        self,
        provider: str,
        reason: FailoverReason,
        *,
        profile_id: str | None = None,
        store: Any | None = None,
    ) -> None:
        """Record a failure and start/extend cooldown.

        Uses *profile_id* as the cooldown key when provided, otherwise
        falls back to *provider*.

        When *store* is provided, schedules fire-and-forget persistence.
        """
        key = self._cooldown_key(provider, profile_id)
        now = self._now()
        with self._lock:
            entry = self._entries.setdefault(key, _CooldownEntry())
            entry.error_count += 1
            entry.failure_counts[reason] = entry.failure_counts.get(reason, 0) + 1
            entry.last_failure = now

            cooldown_secs = self._compute_cooldown(entry.error_count, reason)
            entry.cooldown_end = now + cooldown_secs

        if store is not None:
            try:
                asyncio.get_event_loop().create_task(self.save_state(store))
            except RuntimeError:
                pass  # no event loop — skip persistence

    def mark_success(
        self,
        provider: str,
        *,
        profile_id: str | None = None,
        store: Any | None = None,
    ) -> None:
        """Reset cooldown state after a successful call.

        Uses *profile_id* as the cooldown key when provided, otherwise
        falls back to *provider*.

        When *store* is provided, schedules fire-and-forget persistence.
        """
        key = self._cooldown_key(provider, profile_id)
        with self._lock:
            if key in self._entries:
                del self._entries[key]

        if store is not None:
            try:
                asyncio.get_event_loop().create_task(self.save_state(store))
            except RuntimeError:
                pass  # no event loop — skip persistence

    def is_available(
        self,
        provider: str,
        *,
        profile_id: str | None = None,
    ) -> bool:
        """Return True if the candidate is not in cooldown.

        Uses *profile_id* as the cooldown key when provided, otherwise
        falls back to *provider*.
        """
        key = self._cooldown_key(provider, profile_id)
        now = self._now()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return True
            return now >= entry.cooldown_end

    def cooldown_remaining(
        self,
        provider: str,
        *,
        profile_id: str | None = None,
    ) -> timedelta:
        """Return the remaining cooldown duration.

        Uses *profile_id* as the cooldown key when provided, otherwise
        falls back to *provider*.
        """
        key = self._cooldown_key(provider, profile_id)
        now = self._now()
        with self._lock:
            entry = self._entries.get(key)
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

    # ------------------------------------------------------------------
    # Persistence: save_state / restore_state
    # ------------------------------------------------------------------

    async def save_state(self, store: Any) -> None:
        """Serialize all cooldown entries to the MemoryStore cooldown_state table.

        Converts monotonic timestamps to UTC for persistence.
        """
        import json as _json
        from datetime import datetime, timezone

        now_mono = self._now()
        now_utc = datetime.now(timezone.utc)

        with self._lock:
            entries_snapshot = dict(self._entries)

        for key, entry in entries_snapshot.items():
            # Convert monotonic offsets to UTC timestamps
            cooldown_remaining_secs = max(0.0, entry.cooldown_end - now_mono)
            cooldown_end_utc = now_utc + timedelta(seconds=cooldown_remaining_secs)

            last_failure_offset = max(0.0, now_mono - entry.last_failure)
            last_failure_utc = now_utc - timedelta(seconds=last_failure_offset)

            failure_counts_json = _json.dumps(
                {str(k): v for k, v in entry.failure_counts.items()}
            )

            try:
                await store.set_cooldown_state(
                    profile_id=key,
                    error_count=entry.error_count,
                    cooldown_end_utc=cooldown_end_utc.isoformat(),
                    last_failure_utc=last_failure_utc.isoformat(),
                    failure_counts_json=failure_counts_json,
                )
            except Exception:
                logger.warning("cooldown_save_state_failed: profile_id=%s", key)

        # Delete entries that were removed (mark_success)
        try:
            existing = await store.get_cooldown_states()
            existing_ids = {r["profile_id"] for r in existing}
            active_ids = set(entries_snapshot.keys())
            for stale_id in existing_ids - active_ids:
                try:
                    await store.delete_cooldown_state(stale_id)
                except Exception:
                    pass
        except Exception:
            pass

    async def restore_state(self, store: Any) -> None:
        """Restore cooldown state from the MemoryStore cooldown_state table.

        Converts UTC timestamps back to monotonic offsets. Skips expired records.
        """
        from datetime import datetime, timezone

        try:
            records = await store.get_cooldown_states()
        except Exception:
            logger.warning("cooldown_restore_state_failed")
            return

        now_mono = self._now()
        now_utc = datetime.now(timezone.utc)

        with self._lock:
            for record in records:
                profile_id = record["profile_id"]
                error_count = record["error_count"]
                cooldown_end_utc_str = record["cooldown_end_utc"]
                last_failure_utc_str = record["last_failure_utc"]
                failure_counts_raw = record.get("failure_counts", {})

                try:
                    cooldown_end_utc = datetime.fromisoformat(cooldown_end_utc_str)
                    if cooldown_end_utc.tzinfo is None:
                        cooldown_end_utc = cooldown_end_utc.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue

                # Skip expired records
                if cooldown_end_utc <= now_utc:
                    continue

                try:
                    last_failure_utc = datetime.fromisoformat(last_failure_utc_str)
                    if last_failure_utc.tzinfo is None:
                        last_failure_utc = last_failure_utc.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    last_failure_utc = now_utc

                # Convert UTC to monotonic offsets
                cooldown_remaining = (cooldown_end_utc - now_utc).total_seconds()
                last_failure_ago = (now_utc - last_failure_utc).total_seconds()

                # Reconstruct failure_counts with FailoverReason keys
                failure_counts: dict[FailoverReason, int] = {}
                for reason_str, count in failure_counts_raw.items():
                    try:
                        failure_counts[FailoverReason(reason_str)] = count
                    except ValueError:
                        pass

                entry = _CooldownEntry(
                    error_count=error_count,
                    failure_counts=failure_counts,
                    cooldown_end=now_mono + cooldown_remaining,
                    last_failure=now_mono - max(0.0, last_failure_ago),
                )
                self._entries[profile_id] = entry

        logger.info(
            "cooldown_state_restored: restored_count=%d",
            len(self._entries),
        )


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


class FallbackChain:
    """Model failover chain — tries candidates in priority order.

    Supports two-stage execution when ``auth_profiles`` are provided:

    - **Stage 1**: On RATE_LIMIT, rotate through AuthProfiles of the same
      provider before switching providers.
    - **Stage 2**: When all profiles of a provider are exhausted, move to
      the next provider/model in the fallback list.

    When ``auth_profiles`` is empty/None, behaviour is identical to the
    original single-key fallback (backward compatible).

    - Providers/profiles in cooldown are skipped (recorded as skipped attempts).
    - Non-retriable errors (FORMAT) abort immediately.
    - Retriable errors advance to the next candidate.
    - A successful call resets the candidate's cooldown.
    - Raises FallbackExhaustedError when all candidates fail.
    - Raises ValueError for an empty candidate list.
    """

    def __init__(self, cooldown: CooldownTracker | None = None) -> None:
        self._cooldown = cooldown or CooldownTracker()
        # session_sticky: maps session_id → last successful profile_id
        self._sticky_profiles: dict[str, str] = {}

    @property
    def cooldown(self) -> CooldownTracker:
        """Access the underlying CooldownTracker."""
        return self._cooldown

    # ------------------------------------------------------------------
    # Two-stage candidate builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_two_stage_candidates(
        candidates: list[FallbackCandidate],
        auth_profiles: list[AuthProfile],
    ) -> list[FallbackCandidate]:
        """Build a two-stage candidate list from base candidates + AuthProfiles.

        For each candidate whose provider has matching AuthProfiles, expand it
        into one FallbackCandidate per profile (same model, different
        ``profile_id``).  Candidates whose provider has no matching profiles
        are kept as-is.

        The resulting order interleaves profile rotation *within* a provider
        before moving to the next provider/model — exactly the two-stage
        strategy described in the design doc.

        Returns:
            Expanded candidate list ready for ``execute``.
        """
        if not auth_profiles:
            return list(candidates)

        # Group profiles by provider name
        profiles_by_provider: dict[str, list[AuthProfile]] = defaultdict(list)
        for ap in auth_profiles:
            profiles_by_provider[ap.provider].append(ap)

        result: list[FallbackCandidate] = []
        for cand in candidates:
            provider_profiles = profiles_by_provider.get(cand.provider)
            if provider_profiles:
                # Expand: one candidate per AuthProfile for this provider/model
                for ap in provider_profiles:
                    result.append(
                        FallbackCandidate(
                            provider=cand.provider,
                            model=cand.model,
                            profile_id=ap.profile_id,
                        )
                    )
            else:
                # No profiles for this provider — keep original candidate
                result.append(cand)
        return result

    # ------------------------------------------------------------------
    # Session-sticky reordering
    # ------------------------------------------------------------------

    def _apply_session_sticky(
        self,
        candidates: list[FallbackCandidate],
        session_id: str | None,
    ) -> list[FallbackCandidate]:
        """Reorder candidates so the last successful profile comes first.

        Only applies when *session_id* is provided and a sticky profile is
        recorded for that session.  The sticky profile is moved to the front
        of its provider group (preserving relative order of other candidates).
        """
        if not session_id:
            return candidates
        sticky_pid = self._sticky_profiles.get(session_id)
        if sticky_pid is None:
            return candidates

        # Find the sticky candidate
        sticky_idx: int | None = None
        for i, c in enumerate(candidates):
            if c.profile_id == sticky_pid:
                sticky_idx = i
                break
        if sticky_idx is None:
            return candidates

        # Move sticky candidate to the front of its provider group
        sticky_cand = candidates[sticky_idx]
        reordered = [sticky_cand]
        for i, c in enumerate(candidates):
            if i != sticky_idx:
                reordered.append(c)
        return reordered

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        candidates: list[FallbackCandidate],
        run: Callable[[str, str], Awaitable[AIMessage]],
        *,
        auth_profiles: list[AuthProfile] | None = None,
        session_sticky: bool = False,
        session_id: str | None = None,
    ) -> FallbackResult:
        """Execute the fallback chain.

        Args:
            candidates: Ordered list of (provider, model[, profile_id]) to try.
            run: Async callable ``(provider, model) -> AIMessage``.
            auth_profiles: Optional list of AuthProfiles.  When provided,
                candidates are expanded via ``_build_two_stage_candidates``
                so that profile rotation happens before provider switching.
                When empty or None, behaviour is identical to the original
                single-key fallback.
            session_sticky: When True, prefer the last successful profile_id
                for the given *session_id*.
            session_id: Session identifier for sticky-profile tracking.

        Returns:
            FallbackResult on success.

        Raises:
            ValueError: Empty candidate list.
            FallbackExhaustedError: All candidates failed.
            FailoverError: Non-retriable error encountered (aborts immediately).
        """
        if not candidates:
            raise ValueError("No fallback candidates configured")

        # Stage expansion: build two-stage list when auth_profiles provided
        effective = self._build_two_stage_candidates(
            candidates, auth_profiles or [],
        )

        # Session-sticky reordering
        if session_sticky and session_id:
            effective = self._apply_session_sticky(effective, session_id)

        attempts: list[FallbackAttempt] = []

        for candidate in effective:
            provider, model = candidate.provider, candidate.model
            profile_id = candidate.profile_id

            # Skip candidates in cooldown (key = profile_id or provider)
            if not self._cooldown.is_available(provider, profile_id=profile_id):
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

                self._cooldown.mark_failure(
                    provider, classified.reason, profile_id=profile_id,
                )

                if not classified.is_retriable():
                    # Non-retriable (FORMAT) — abort immediately
                    raise classified from exc

                # Retriable — try next candidate
                continue

            # Success
            duration = timedelta(seconds=time.monotonic() - start)
            self._cooldown.mark_success(provider, profile_id=profile_id)

            # Record sticky profile for session
            if session_sticky and session_id and profile_id is not None:
                self._sticky_profiles[session_id] = profile_id

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
