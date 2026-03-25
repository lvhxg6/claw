"""Property-based tests for PathPolicy.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import pathlib
import tempfile

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from smartclaw.security.path_policy import PathDeniedError, PathPolicy

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe path component: alphanumeric + underscore, non-empty
_safe_name = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,15}", fullmatch=True)

# Resolved tmp dir (handles macOS /tmp -> /private/tmp)
_resolved_tmp = str(pathlib.Path(tempfile.gettempdir()).resolve())


# ---------------------------------------------------------------------------
# Property 17: PathPolicy blacklist-first evaluation
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 17: PathPolicy blacklist-first evaluation
@given(path_suffix=_safe_name)
@settings(max_examples=100)
def test_blacklist_first_evaluation(path_suffix: str) -> None:
    """For any path matching both whitelist and blacklist, is_allowed returns False.
    For any path not matching any whitelist pattern (when whitelist is non-empty),
    is_allowed returns False.

    **Validates: Requirements 6.2, 6.3**
    """
    # Use a subdirectory structure so ** globs work correctly
    # The path is under {tmp}/blocked/{suffix}/file.txt
    blocked_dir = f"{_resolved_tmp}/blocked"
    path = f"{blocked_dir}/{path_suffix}/file.txt"

    # Case 1: path matches both whitelist and blacklist → denied
    policy_both = PathPolicy(
        allowed_patterns=[f"{_resolved_tmp}/**"],
        denied_patterns=[f"{blocked_dir}/**"],
    )
    assert policy_both.is_allowed(path) is False

    # Case 2: whitelist non-empty, path doesn't match whitelist → denied
    policy_no_match = PathPolicy(
        allowed_patterns=["/var/data/**"],
        denied_patterns=[],
    )
    assert policy_no_match.is_allowed(path) is False


# ---------------------------------------------------------------------------
# Property 18: PathPolicy path normalization
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 18: PathPolicy path normalization
@given(name=_safe_name)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_path_normalization(name: str, tmp_path: pathlib.Path) -> None:
    """For any relative path and its absolute equivalent, PathPolicy produces
    the same is_allowed result for both.

    **Validates: Requirements 6.5, 6.6**
    """
    # Create a real file so resolve() works consistently
    target = tmp_path / name
    target.touch()

    abs_path = str(target.resolve())
    rel_path = str(target)

    resolved_base = str(tmp_path.resolve())
    policy = PathPolicy(allowed_patterns=[resolved_base, f"{resolved_base}/**"])
    assert policy.is_allowed(rel_path) == policy.is_allowed(abs_path)


# ---------------------------------------------------------------------------
# Property 19: PathPolicy check/is_allowed consistency
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 19: PathPolicy check/is_allowed consistency
@given(name=_safe_name)
@settings(max_examples=100)
def test_check_is_allowed_consistency(name: str) -> None:
    """For any path string, check(path) raises PathDeniedError iff is_allowed(path)
    returns False.

    **Validates: Requirements 6.8**
    """
    path = f"{_resolved_tmp}/check_{name}"
    policy = PathPolicy()

    allowed = policy.is_allowed(path)
    raised = False
    try:
        policy.check(path)
    except PathDeniedError:
        raised = True

    assert raised == (not allowed)


# ---------------------------------------------------------------------------
# Property 20: PathPolicy glob pattern matching
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 20: PathPolicy glob pattern matching
@given(name=_safe_name)
@settings(max_examples=100)
def test_glob_pattern_matching(name: str) -> None:
    """For any glob pattern in whitelist and any matching path, is_allowed returns True
    (assuming no blacklist match). For any glob in blacklist and any matching path,
    is_allowed returns False.

    **Validates: Requirements 6.9**
    """
    # Use subdirectory-based patterns so ** globs work correctly
    allow_dir = f"{_resolved_tmp}/allowed_glob"
    deny_dir = f"{_resolved_tmp}/denied_glob"
    allow_path = f"{allow_dir}/{name}"
    deny_path = f"{deny_dir}/{name}"

    # Whitelist glob match → allowed
    policy_allow = PathPolicy(allowed_patterns=[f"{allow_dir}/**"])
    assert policy_allow.is_allowed(allow_path) is True

    # Blacklist glob match → denied
    policy_deny = PathPolicy(denied_patterns=[f"{deny_dir}/**"])
    assert policy_deny.is_allowed(deny_path) is False
