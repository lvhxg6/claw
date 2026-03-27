"""Property-based tests for AuthProfile and FallbackChain (Properties 6–10).

Feature: smartclaw-provider-context-optimization
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings
from langchain_core.messages import AIMessage

from smartclaw.providers.config import AuthProfile, ModelConfig
from smartclaw.providers.fallback import (
    CooldownTracker,
    FailoverReason,
    FallbackCandidate,
    FallbackChain,
    FallbackExhaustedError,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Safe identifier-like strings
_identifier = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() == s and len(s) > 0)

# Environment variable key names
_env_keys = st.from_regex(r"[A-Z][A-Z0-9_]{2,20}", fullmatch=True)

# Optional base URLs
_base_urls = st.one_of(
    st.none(),
    st.builds(
        lambda h: f"https://{h}.example.com/v1",
        h=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    ),
)

# AuthProfile strategy
_auth_profiles = st.builds(
    AuthProfile,
    profile_id=_identifier,
    provider=_identifier,
    env_key=_env_keys,
    base_url=_base_urls,
)

# Provider/model format strings (no slash in parts)
_provider_name = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)
_model_name = st.from_regex(r"[a-z][a-z0-9_-]{0,15}", fullmatch=True)
_model_ref = st.builds(lambda p, m: f"{p}/{m}", p=_provider_name, m=_model_name)


class _StatusError(Exception):
    """Fake HTTP error with a status_code attribute."""

    def __init__(self, status_code: int, message: str = "rate limit") -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Property 6: AuthProfile 配置序列化往返
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 6: AuthProfile 配置序列化往返
class TestAuthProfileSerializationRoundTrip:
    """**Validates: Requirements 2.1**

    For any ModelConfig with auth_profiles, serializing to dict and back
    should preserve all fields.
    """

    @given(
        profiles=st.lists(
            _auth_profiles,
            min_size=0,
            max_size=5,
        ),
        session_sticky=st.booleans(),
    )
    @settings(max_examples=100)
    def test_model_config_round_trip(
        self,
        profiles: list[AuthProfile],
        session_sticky: bool,
    ) -> None:
        """Serializing ModelConfig to dict and back preserves auth_profiles."""
        config = ModelConfig(
            auth_profiles=profiles,
            session_sticky=session_sticky,
        )

        # Serialize to dict
        data = config.model_dump()

        # Deserialize back
        restored = ModelConfig(**data)

        # Verify auth_profiles preserved
        assert len(restored.auth_profiles) == len(config.auth_profiles)
        for orig, rest in zip(config.auth_profiles, restored.auth_profiles):
            assert rest.profile_id == orig.profile_id
            assert rest.provider == orig.provider
            assert rest.env_key == orig.env_key
            assert rest.base_url == orig.base_url

        # Verify session_sticky preserved
        assert restored.session_sticky == config.session_sticky


# ---------------------------------------------------------------------------
# Property 7: 两阶段 FallbackChain 执行顺序
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 7: 两阶段 FallbackChain 执行顺序
class TestTwoStageFallbackOrder:
    """**Validates: Requirements 2.2, 2.4, 2.5**

    When primary provider has multiple AuthProfiles and first fails with
    RATE_LIMIT, chain should try next profile of same provider before
    different provider.
    """

    @given(
        n_profiles=st.integers(min_value=2, max_value=4),
        n_fallbacks=st.integers(min_value=1, max_value=3),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_profile_rotation_before_provider_switch(
        self,
        n_profiles: int,
        n_fallbacks: int,
    ) -> None:
        """On RATE_LIMIT, chain tries next AuthProfile of same provider first."""
        primary_provider = "primary_prov"
        primary_model = "primary_model"

        # Build auth profiles for the primary provider
        profiles = [
            AuthProfile(
                profile_id=f"profile_{i}",
                provider=primary_provider,
                env_key=f"KEY_{i}",
            )
            for i in range(n_profiles)
        ]

        # Build candidates: primary + fallbacks
        candidates = [FallbackCandidate(primary_provider, primary_model)]
        for i in range(n_fallbacks):
            candidates.append(FallbackCandidate(f"fallback_{i}", f"fb_model_{i}"))

        call_order: list[tuple[str, str]] = []

        # All primary profiles fail with RATE_LIMIT, first fallback succeeds
        async def run(provider: str, model: str) -> AIMessage:
            call_order.append((provider, model))
            if provider == primary_provider:
                raise _StatusError(429, "rate limit")
            return AIMessage(content="ok")

        chain = FallbackChain()
        result = await chain.execute(
            candidates, run, auth_profiles=profiles,
        )

        # Verify: all primary profiles were tried before any fallback
        primary_calls = [
            (p, m) for p, m in call_order if p == primary_provider
        ]
        fallback_calls = [
            (p, m) for p, m in call_order if p != primary_provider
        ]

        # All primary profiles should have been attempted
        assert len(primary_calls) == n_profiles

        # Primary calls should come before fallback calls in call_order
        if fallback_calls:
            last_primary_idx = max(
                i for i, (p, _) in enumerate(call_order) if p == primary_provider
            )
            first_fallback_idx = min(
                i for i, (p, _) in enumerate(call_order) if p != primary_provider
            )
            assert last_primary_idx < first_fallback_idx

        # Result should be from a fallback provider
        assert result.provider != primary_provider

    @given(
        n_profiles=st.integers(min_value=2, max_value=4),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_all_profiles_exhausted_then_fallback_exhausted(
        self,
        n_profiles: int,
    ) -> None:
        """When all profiles and fallbacks fail, FallbackExhaustedError is raised."""
        primary_provider = "primary_prov"
        profiles = [
            AuthProfile(
                profile_id=f"profile_{i}",
                provider=primary_provider,
                env_key=f"KEY_{i}",
            )
            for i in range(n_profiles)
        ]

        candidates = [FallbackCandidate(primary_provider, "model")]

        async def run(provider: str, model: str) -> AIMessage:
            raise _StatusError(429, "rate limit")

        chain = FallbackChain()
        with pytest.raises(FallbackExhaustedError) as exc_info:
            await chain.execute(candidates, run, auth_profiles=profiles)

        # All profiles should have been attempted
        non_skipped = [a for a in exc_info.value.attempts if not a.skipped]
        assert len(non_skipped) == n_profiles


# ---------------------------------------------------------------------------
# Property 8: CooldownTracker profile_id 独立性
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 8: CooldownTracker profile_id 独立性
class TestCooldownProfileIndependence:
    """**Validates: Requirements 2.3**

    Marking failure on one profile_id should not affect availability of
    another profile_id for the same provider.
    """

    @given(
        provider=_identifier,
        profile_a=_identifier,
        profile_b=_identifier,
        reason=st.sampled_from(list(FailoverReason)),
    )
    @settings(max_examples=100)
    def test_independent_cooldown_per_profile(
        self,
        provider: str,
        profile_a: str,
        profile_b: str,
        reason: FailoverReason,
    ) -> None:
        """Failure on profile_a does not put profile_b in cooldown."""
        # Ensure distinct profile_ids
        if profile_a == profile_b:
            profile_b = profile_b + "_other"

        t = 0.0
        tracker = CooldownTracker(now_func=lambda: t)

        # Mark failure on profile_a
        tracker.mark_failure(provider, reason, profile_id=profile_a)

        # profile_a should be in cooldown
        assert not tracker.is_available(provider, profile_id=profile_a)
        assert tracker.cooldown_remaining(provider, profile_id=profile_a) > timedelta(0)

        # profile_b should still be available
        assert tracker.is_available(provider, profile_id=profile_b)
        assert tracker.cooldown_remaining(provider, profile_id=profile_b) == timedelta(0)


# ---------------------------------------------------------------------------
# Property 9: 空 AuthProfile 向后兼容
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 9: 空 AuthProfile 向后兼容
class TestEmptyAuthProfileBackwardCompat:
    """**Validates: Requirements 2.7**

    When auth_profiles is empty, behavior should be identical to single-key
    fallback: candidates are tried in order by provider/model without any
    profile-level rotation.
    """

    @given(
        n_candidates=st.integers(min_value=1, max_value=5),
        success_idx=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_empty_profiles_same_as_single_key(
        self,
        n_candidates: int,
        success_idx: int,
    ) -> None:
        """With empty auth_profiles, candidates tried in order like single-key fallback."""
        success_idx = min(success_idx, n_candidates - 1)

        candidates = [
            FallbackCandidate(f"provider_{i}", f"model_{i}")
            for i in range(n_candidates)
        ]

        # Run with empty auth_profiles
        call_order_with_empty: list[tuple[str, str]] = []

        async def run_empty(provider: str, model: str) -> AIMessage:
            call_order_with_empty.append((provider, model))
            idx = len(call_order_with_empty) - 1
            if idx < success_idx:
                raise _StatusError(429, "rate limit")
            return AIMessage(content="ok")

        chain_empty = FallbackChain()
        result_empty = await chain_empty.execute(
            candidates, run_empty, auth_profiles=[],
        )

        # Run without auth_profiles (None)
        call_order_without: list[tuple[str, str]] = []

        async def run_without(provider: str, model: str) -> AIMessage:
            call_order_without.append((provider, model))
            idx = len(call_order_without) - 1
            if idx < success_idx:
                raise _StatusError(429, "rate limit")
            return AIMessage(content="ok")

        chain_without = FallbackChain()
        result_without = await chain_without.execute(
            candidates, run_without,
        )

        # Both should have identical call order
        assert call_order_with_empty == call_order_without

        # Both should succeed on the same provider/model
        assert result_empty.provider == result_without.provider
        assert result_empty.model == result_without.model

        # Same number of attempts
        assert len(result_empty.attempts) == len(result_without.attempts)


# ---------------------------------------------------------------------------
# Property 10: session_sticky 优先使用上次成功的 AuthProfile
# ---------------------------------------------------------------------------

# Feature: smartclaw-provider-context-optimization, Property 10: session_sticky 优先使用上次成功的 AuthProfile
class TestSessionStickyProfile:
    """**Validates: Requirements 2.8**

    After successful call with a profile, subsequent calls in same session
    should try that profile first.
    """

    @given(
        n_profiles=st.integers(min_value=2, max_value=4),
        first_success_idx=st.integers(min_value=0, max_value=3),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_sticky_profile_tried_first(
        self,
        n_profiles: int,
        first_success_idx: int,
    ) -> None:
        """After success with profile X, next call tries X first."""
        first_success_idx = min(first_success_idx, n_profiles - 1)
        provider = "sticky_prov"
        session_id = "test_session"

        profiles = [
            AuthProfile(
                profile_id=f"profile_{i}",
                provider=provider,
                env_key=f"KEY_{i}",
            )
            for i in range(n_profiles)
        ]

        candidates = [FallbackCandidate(provider, "model")]

        # First call: profiles before first_success_idx fail, then succeed
        first_call_order: list[str] = []
        call_count = 0

        async def run_first(prov: str, model: str) -> AIMessage:
            nonlocal call_count
            idx = call_count
            call_count += 1
            profile_id = f"profile_{idx}"
            first_call_order.append(profile_id)
            if idx < first_success_idx:
                raise _StatusError(429, "rate limit")
            return AIMessage(content="ok")

        chain = FallbackChain()
        await chain.execute(
            candidates,
            run_first,
            auth_profiles=profiles,
            session_sticky=True,
            session_id=session_id,
        )

        successful_profile = f"profile_{first_success_idx}"

        # Second call: track which profile is tried first
        second_call_order: list[str] = []
        second_call_count = 0

        async def run_second(prov: str, model: str) -> AIMessage:
            nonlocal second_call_count
            second_call_order.append(f"call_{second_call_count}")
            second_call_count += 1
            return AIMessage(content="ok")

        # Build a new chain reusing the same sticky state
        # The chain's _sticky_profiles should have the session recorded
        result = await chain.execute(
            candidates,
            run_second,
            auth_profiles=profiles,
            session_sticky=True,
            session_id=session_id,
        )

        # The successful profile from first call should be the provider used
        # (since it's tried first and succeeds immediately)
        # Verify the chain's internal sticky state
        assert chain._sticky_profiles.get(session_id) == successful_profile
