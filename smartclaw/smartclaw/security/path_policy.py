"""PathPolicy — whitelist/blacklist path security engine.

Evaluates filesystem paths against configurable allow/deny glob patterns.
Blacklist is always evaluated first; default sensitive paths are always denied.
"""

from __future__ import annotations

import fnmatch
import pathlib

# Default denied paths (always blocked)
DEFAULT_DENIED_PATHS: list[str] = [
    "~/.ssh/**",
    "~/.gnupg/**",
    "~/.aws/**",
    "~/.config/gcloud/**",
    "/etc/shadow",
    "/etc/passwd",
]


class PathDeniedError(Exception):
    """Raised when a filesystem path violates the security policy."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Access denied — path '{path}' is not allowed by security policy")


class PathPolicy:
    """Path security policy engine based on whitelist/blacklist glob patterns.

    Evaluation order:
    1. Resolve and normalize the path (resolve symlinks).
    2. Check blacklist — if any pattern matches, deny.
    3. If whitelist is non-empty, check whitelist — if no pattern matches, deny.
    4. Otherwise, allow.
    """

    def __init__(
        self,
        allowed_patterns: list[str] | None = None,
        denied_patterns: list[str] | None = None,
    ) -> None:
        self._allowed_patterns = self._normalize_patterns(allowed_patterns or [])
        # Always include default denied paths
        user_denied = denied_patterns or []
        all_denied = list(DEFAULT_DENIED_PATHS) + user_denied
        self._denied_patterns = self._normalize_patterns(all_denied)

    @staticmethod
    def _normalize_patterns(patterns: list[str]) -> list[str]:
        """Expand ~ and resolve base directories in patterns."""
        result: list[str] = []
        for pattern in patterns:
            # Expand ~
            if pattern.startswith("~"):
                home = str(pathlib.Path.home())
                pattern = home + pattern[1:]

            # For patterns without glob chars, resolve fully
            if not any(c in pattern for c in ("*", "?", "[")):
                resolved = str(pathlib.Path(pattern).resolve())
                result.append(resolved)
            else:
                # Split at first glob char, resolve the directory prefix, reattach glob suffix
                for i, c in enumerate(pattern):
                    if c in ("*", "?", "["):
                        prefix = pattern[:i].rstrip("/")
                        suffix = pattern[i:]
                        if prefix:
                            resolved_prefix = str(pathlib.Path(prefix).resolve())
                            result.append(f"{resolved_prefix}/{suffix}")
                        else:
                            result.append(pattern)
                        break
            
        return result

    def _resolve(self, path: str) -> str:
        """Resolve a path to its absolute, symlink-resolved form."""
        p = pathlib.Path(path).expanduser().resolve()
        return str(p)

    def _matches(self, resolved_path: str, pattern: str) -> bool:
        """Check if a resolved path matches a glob pattern."""
        return fnmatch.fnmatch(resolved_path, pattern)

    def is_allowed(self, path: str) -> bool:
        """Check whether *path* is allowed by the policy.

        Returns True if allowed, False if denied.
        """
        resolved = self._resolve(path)

        # Blacklist first
        for pattern in self._denied_patterns:
            if self._matches(resolved, pattern):
                return False

        # Whitelist check (only if whitelist is non-empty)
        if self._allowed_patterns:
            for pattern in self._allowed_patterns:
                if self._matches(resolved, pattern):
                    return True
            # No whitelist pattern matched
            return False

        # No whitelist configured — allow
        return True

    def check(self, path: str) -> None:
        """Raise ``PathDeniedError`` if *path* is not allowed."""
        if not self.is_allowed(path):
            # Log security event for audit
            import structlog
            logger = structlog.get_logger(component="security.path_policy")
            logger.warning("path_access_denied", path=path, denied_patterns=self._denied_patterns)
            raise PathDeniedError(path)
