"""Provider protocol + registry.

A Provider knows how to read a local CLI's credentials and fetch a usage
snapshot. ``fetch()`` must never raise: on any failure it returns a
``UsageSnapshot`` whose ``error`` field explains the problem with a fix hint.

Adding a new service = drop a module here and register it in ``build_providers``.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import UsageSnapshot


@runtime_checkable
class Provider(Protocol):
    id: str
    display_name: str

    def fetch(self) -> UsageSnapshot:  # pragma: no cover - protocol
        ...


def build_providers(
    enabled: dict[str, bool] | None = None,
    deepseek_api_key: str = "",
) -> list[Provider]:
    """Instantiate the registered providers.

    ``enabled`` maps provider id -> bool; missing ids default to enabled.
    ``deepseek_api_key`` is injected into DeepSeekProvider (empty -> provider
    falls back to the DEEPSEEK_API_KEY env var).
    """
    from .claude import ClaudeProvider
    from .codex import CodexProvider
    from .deepseek import DeepSeekProvider

    enabled = enabled or {}
    registry: list[Provider] = [
        ClaudeProvider(),
        CodexProvider(),
        DeepSeekProvider(api_key=deepseek_api_key or None),
    ]
    return [p for p in registry if enabled.get(p.id, True)]
