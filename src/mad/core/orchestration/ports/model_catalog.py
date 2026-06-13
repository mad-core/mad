"""ModelCatalog port — provider-agnostic model discovery.

Implementations live in mad.adapters.outbound.agents. The port is
intentionally narrow: one async method returning the full
provider→models mapping. Discovery strategy (CLI probe, static
fallback) is entirely the adapter's concern; discovery errors are
swallowed by the adapter and replaced with a fallback list so callers
never see an exception.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelCatalog(Protocol):
    async def discover(self) -> dict[str, list[str]]: ...
