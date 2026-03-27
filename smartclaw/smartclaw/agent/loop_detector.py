"""Loop detection via hash-based sliding window.

Provides :class:`LoopDetector` which tracks recent tool-call hashes in a
fixed-size sliding window and returns a :class:`LoopStatus` indicating
whether the agent appears to be stuck in a repetitive loop.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from enum import Enum


class LoopStatus(str, Enum):
    """Status returned by :meth:`LoopDetector.record`."""

    OK = "ok"
    WARN = "warn"
    STOP = "stop"


class LoopDetector:
    """Detect repetitive tool-call patterns using a hash sliding window.

    Parameters:
        window_size: Maximum number of recent hashes to retain.
        warn_threshold: Hash repeat count that triggers a warning.
        stop_threshold: Hash repeat count that forces a stop.
    """

    def __init__(
        self,
        window_size: int = 20,
        warn_threshold: int = 3,
        stop_threshold: int = 5,
    ) -> None:
        self._window: deque[str] = deque(maxlen=window_size)
        self._window_size = window_size
        self._warn_threshold = warn_threshold
        self._stop_threshold = stop_threshold

    @staticmethod
    def compute_hash(tool_name: str, tool_args: dict) -> str:
        """Return a deterministic 16-char hex hash for a tool call.

        The hash is computed by JSON-serialising ``{"name": tool_name,
        "args": tool_args}`` with sorted keys, then taking the first 16
        hex characters of the SHA-256 digest.
        """
        payload = json.dumps({"name": tool_name, "args": tool_args}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def record(self, tool_name: str, tool_args: dict) -> LoopStatus:
        """Record a tool call and return the current loop status.

        The tool call is hashed via :meth:`compute_hash`, appended to the
        internal sliding window, and the occurrence count within the window
        is compared against the configured thresholds.
        """
        h = self.compute_hash(tool_name, tool_args)
        self._window.append(h)
        count = self._window.count(h)
        if count >= self._stop_threshold:
            return LoopStatus.STOP
        if count >= self._warn_threshold:
            return LoopStatus.WARN
        return LoopStatus.OK
