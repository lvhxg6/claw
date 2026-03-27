"""L5 ContextEngine plugin architecture.

Public API:
    ContextEngine         — abstract interface for context lifecycle management
    LegacyContextEngine   — default implementation wrapping AutoSummarizer
    ContextEngineRegistry — registry for discovering and creating engines
"""

from smartclaw.context_engine.interface import ContextEngine
from smartclaw.context_engine.legacy import LegacyContextEngine
from smartclaw.context_engine.registry import ContextEngineRegistry

__all__ = [
    "ContextEngine",
    "ContextEngineRegistry",
    "LegacyContextEngine",
]
