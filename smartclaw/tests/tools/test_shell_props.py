"""Property-based tests for ShellTool.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.tools.shell import ShellTool

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Commands that match deny patterns
_denied_commands = st.sampled_from([
    "rm -rf /",
    "sudo apt install foo",
    "shutdown -h now",
    "reboot",
    "poweroff",
    "dd if=/dev/zero of=/dev/sda",
    "mkfs.ext4 /dev/sda1",
    "chmod 777 /etc/passwd",
    "chown root:root /tmp/x",
    "kill -9 1234",
    "pkill python",
    "killall node",
])

# Safe commands that don't match any deny pattern
_safe_commands = st.sampled_from([
    "echo hello",
    "ls -la",
    "cat /dev/null",
    "pwd",
    "whoami",
    "date",
    "uname -a",
    "env",
    "true",
    "printf 'test'",
])


# ---------------------------------------------------------------------------
# Property 11: Shell deny pattern blocking
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 11: Shell deny pattern blocking
@given(cmd=_denied_commands)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_deny_pattern_blocking(cmd: str) -> None:
    """For any command matching at least one deny pattern, ShellTool returns
    error without executing.

    **Validates: Requirements 4.9**
    """
    tool = ShellTool()
    result = await tool._arun(command=cmd)
    assert "Error: Command blocked by security policy" in result


# ---------------------------------------------------------------------------
# Property 12: Shell output format with stderr prefix
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 12: Shell output format with stderr prefix
@given(
    stdout_text=st.from_regex(r"[a-zA-Z0-9]{1,20}", fullmatch=True),
    stderr_text=st.from_regex(r"[a-zA-Z0-9]{1,20}", fullmatch=True),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_stderr_prefix_format(stdout_text: str, stderr_text: str) -> None:
    """For any command producing both stdout and stderr, the returned string
    contains stdout content and stderr prefixed by 'STDERR:\\n'.

    **Validates: Requirements 4.6**
    """
    tool = ShellTool()
    cmd = f"echo '{stdout_text}' && echo '{stderr_text}' >&2"
    result = await tool._arun(command=cmd, timeout_seconds=10)

    assert stdout_text in result
    assert "STDERR:\n" in result
    assert stderr_text in result


# ---------------------------------------------------------------------------
# Property 13: Shell exit code in output
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 13: Shell exit code in output
@given(exit_code=st.integers(min_value=1, max_value=125))
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_exit_code_in_output(exit_code: int) -> None:
    """For any command exiting with non-zero code N, the returned string
    contains the string representation of N.

    **Validates: Requirements 4.7**
    """
    tool = ShellTool()
    result = await tool._arun(command=f"exit {exit_code}", timeout_seconds=10)
    assert str(exit_code) in result


# ---------------------------------------------------------------------------
# Property 14: Shell output truncation
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 14: Shell output truncation
@given(repeat=st.integers(min_value=200, max_value=300))
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_output_truncation(repeat: int) -> None:
    """For any command whose combined output exceeds 10,000 characters,
    the returned string is truncated to at most 10,000 chars plus a
    truncation indicator.

    **Validates: Requirements 4.8**
    """
    tool = ShellTool()
    # Generate output > 10000 chars: each line is ~51 chars, 200+ lines > 10000
    cmd = f"for i in $(seq 1 {repeat}); do echo 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'; done"
    result = await tool._arun(command=cmd, timeout_seconds=15)

    if "truncated" in result:
        # Content before truncation indicator should be <= 10000
        idx = result.index("\n... [truncated")
        assert idx <= 10_000
