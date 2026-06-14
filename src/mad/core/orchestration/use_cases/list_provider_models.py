from __future__ import annotations

from dataclasses import dataclass

from mad.core.orchestration.ports.model_catalog import ModelCatalog


class InvalidModelError(ValueError):
    """Requested model is not in the provider's advertised catalog.

    Inherits ValueError (like InvalidDispatchPolicy); mapped to HTTP 422.
    """

    def __init__(self, provider: str, model: str, available: list[str]) -> None:
        self.provider = provider
        self.model = model
        self.available = available
        super().__init__(
            f"Model {model!r} is not available for provider {provider!r}. Available: {available}"
        )


@dataclass(frozen=True)
class ListProviderModelsOutput:
    catalog: dict[str, list[str]]


class ListProviderModelsUseCase:
    def __init__(self, catalog: ModelCatalog) -> None:
        self._catalog = catalog

    async def execute(self) -> ListProviderModelsOutput:
        return ListProviderModelsOutput(catalog=await self._catalog.discover())

    async def validate_model(self, provider: str, model: str) -> None:
        """Raise InvalidModelError if model is not in the provider's catalog."""
        catalog = (await self.execute()).catalog
        self.validate_against(catalog, provider, model)

    @staticmethod
    def validate_against(catalog: dict[str, list[str]], provider: str, model: str) -> None:
        if model not in catalog.get(provider, []):
            raise InvalidModelError(provider, model, catalog.get(provider, []))
