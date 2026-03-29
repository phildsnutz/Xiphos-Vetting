"""
Evidence source metadata registry.

This module classifies connector and derived evidence into a small set of
source classes so Helios can distinguish:

- public connectors
- gated federal sources
- customer artifacts
- rules / derived analysis

The registry is intentionally lightweight and backward compatible. Any source
not yet listed falls back to a conservative public/third-party default.
"""

from dataclasses import dataclass, asdict

from .connector_registry import CONNECTOR_REGISTRY, get_source_metadata_defaults


@dataclass(frozen=True)
class EvidenceSourceMetadata:
    source_class: str
    authority_level: str
    access_model: str

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_SOURCE_METADATA = EvidenceSourceMetadata(
    source_class="public_connector",
    authority_level="third_party_public",
    access_model="public_api",
)


SOURCE_METADATA: dict[str, EvidenceSourceMetadata] = {
    name: EvidenceSourceMetadata(
        source_class=entry.source_class,
        authority_level=entry.authority_level,
        access_model=entry.access_model,
    )
    for name, entry in CONNECTOR_REGISTRY.items()
}


def get_source_metadata(
    source: str,
    *,
    source_class: str = "",
    authority_level: str = "",
    access_model: str = "",
) -> dict:
    """Return normalized metadata for a source, preserving explicit overrides."""
    if source:
        base_defaults = get_source_metadata_defaults(source)
        base = EvidenceSourceMetadata(**base_defaults)
    else:
        base = DEFAULT_SOURCE_METADATA
    return {
        "source_class": source_class or base.source_class,
        "authority_level": authority_level or base.authority_level,
        "access_model": access_model or base.access_model,
    }
