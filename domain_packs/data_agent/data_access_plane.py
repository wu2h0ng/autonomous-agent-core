from __future__ import annotations

from .domain_contracts import ProviderContract


class ProviderRegistry:
    def __init__(self, providers: tuple[ProviderContract, ...] = ()) -> None:
        self._providers = {provider.provider_id: provider for provider in providers}

    def get(self, provider_id: str) -> ProviderContract:
        if provider_id not in self._providers:
            raise KeyError(f"Unknown provider contract: {provider_id}")
        return self._providers[provider_id]

    def choose_for_schemas(self, schemas: tuple[str, ...]) -> ProviderContract:
        for provider in self._providers.values():
            if all(schema in provider.allowed_schemas for schema in schemas):
                return provider
        raise KeyError(f"No provider can satisfy schemas: {', '.join(schemas)}")

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
