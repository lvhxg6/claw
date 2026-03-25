"""Unit tests for PathPolicy."""

from __future__ import annotations

import os
import pathlib

import pytest

from smartclaw.security.path_policy import DEFAULT_DENIED_PATHS, PathDeniedError, PathPolicy


class TestDefaultDeniedPaths:
    """Test that default sensitive paths are blocked (Req 6.4)."""

    def test_ssh_dir_blocked(self) -> None:
        policy = PathPolicy()
        home = str(pathlib.Path.home())
        assert policy.is_allowed(f"{home}/.ssh/id_rsa") is False

    def test_aws_dir_blocked(self) -> None:
        policy = PathPolicy()
        home = str(pathlib.Path.home())
        assert policy.is_allowed(f"{home}/.aws/credentials") is False

    def test_gnupg_dir_blocked(self) -> None:
        policy = PathPolicy()
        home = str(pathlib.Path.home())
        assert policy.is_allowed(f"{home}/.gnupg/secring.gpg") is False

    def test_etc_shadow_blocked(self) -> None:
        policy = PathPolicy()
        assert policy.is_allowed("/etc/shadow") is False

    def test_etc_passwd_blocked(self) -> None:
        policy = PathPolicy()
        assert policy.is_allowed("/etc/passwd") is False


class TestSymlinkBypass:
    """Test symlink bypass prevention (Req 6.5)."""

    def test_symlink_to_denied_path_is_blocked(self, tmp_path: pathlib.Path) -> None:
        """A symlink pointing to a denied path should be blocked."""
        # Create a symlink pointing to /etc/shadow
        link = tmp_path / "sneaky_link"
        try:
            link.symlink_to("/etc/shadow")
        except OSError:
            pytest.skip("Cannot create symlink (permissions)")

        policy = PathPolicy()
        assert policy.is_allowed(str(link)) is False


class TestEmptyWhitelist:
    """Test empty whitelist allows all non-blacklisted paths."""

    def test_non_blacklisted_path_allowed(self, tmp_path: pathlib.Path) -> None:
        policy = PathPolicy()
        test_file = tmp_path / "hello.txt"
        test_file.touch()
        assert policy.is_allowed(str(test_file)) is True


class TestPathDeniedError:
    """Test PathDeniedError exception."""

    def test_error_has_path_attribute(self) -> None:
        err = PathDeniedError("/secret/file")
        assert err.path == "/secret/file"

    def test_error_message_format(self) -> None:
        err = PathDeniedError("/secret/file")
        assert "Access denied" in str(err)
        assert "/secret/file" in str(err)

    def test_check_raises_for_denied_path(self) -> None:
        policy = PathPolicy()
        with pytest.raises(PathDeniedError):
            policy.check("/etc/shadow")
