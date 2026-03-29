"""
Lightweight entity resolution engine for the Xiphos vendor vetting platform.

Resolves entities discovered across multiple OSINT connectors into a unified
knowledge graph. Uses deterministic identifier matching (CIK, LEI, UEI, CAGE)
and probabilistic fuzzy name matching (Jaro-Winkler).

No external dependencies beyond Python stdlib.
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib
import re
from datetime import datetime
from ofac import jaro_winkler


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ResolvedEntity:
    """A canonical entity in the knowledge graph."""
    id: str                          # UUID-like identifier
    canonical_name: str              # Best/most authoritative name
    entity_type: str                 # company, person, government, unknown
    aliases: list[str] = field(default_factory=list)  # All known name variants
    identifiers: dict = field(default_factory=dict)   # {cik, lei, uei, cage, ...}
    country: str = ""
    relationships: list[dict] = field(default_factory=list)  # Connections to other entities
    sources: list[str] = field(default_factory=list)  # Which connectors contributed
    confidence: float = 0.0          # 0-1 resolution confidence
    last_updated: str = ""

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "aliases": self.aliases,
            "identifiers": self.identifiers,
            "country": self.country,
            "relationships": self.relationships,
            "sources": self.sources,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
        }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """
    Normalize a company name for matching.
    - Uppercase
    - Strip common suffixes
    - Remove punctuation
    """
    if not name:
        return ""

    s = name.upper().strip()

    # Strip common legal suffixes
    suffixes = [
        r'\bINC\.?$', r'\bINCORPORATED$',
        r'\bLLC\.?$', r'\bL\.L\.C\.?$',
        r'\bLTD\.?$', r'\bLIMITED$',
        r'\bPLC\.?$',
        r'\bCORP\.?$', r'\bCORPORATION$',
        r'\bCO\.?$', r'\bCOMPANY$',
        r'\bPTY\.?$', r'\bPROPRIETARY$',
        r'\bGMBH$', r'\bSARL$', r'\bSRL$',
        r'\bAG$', r'\bS\.A\.?$', r'\bN\.V\.?$',
    ]

    for suffix in suffixes:
        s = re.sub(suffix, "", s)

    # Strip "THE" prefix
    s = re.sub(r'^\bTHE\s+', '', s)

    # Remove punctuation except spaces
    s = re.sub(r'[^\w\s]', '', s)

    # Normalize whitespace
    s = re.sub(r'\s+', ' ', s).strip()

    return s


def generate_entity_id(name: str, identifiers: dict) -> str:
    """Generate a stable entity ID from identifiers or name."""
    # Prefer identifier-based ID (deterministic)
    for key in ["cik", "lei", "uei", "cage"]:
        if key in identifiers and identifiers[key]:
            return f"{key}:{identifiers[key]}"

    # Fall back to name hash (when no identifiers available)
    normalized = normalize_name(name)
    hash_val = hashlib.md5(normalized.encode()).hexdigest()[:12]
    return f"entity:{hash_val}"


def extract_identifiers(enrichment_data: dict) -> dict:
    """Extract known identifiers from enrichment findings."""
    identifiers = {}

    # Top-level identifiers from enrichment report
    if "identifiers" in enrichment_data:
        identifiers.update(enrichment_data["identifiers"])

    # Parse identifiers from raw_data fields in findings
    for finding in enrichment_data.get("findings", []):
        raw = finding.get("raw_data", {})
        for key in ["cik", "lei", "uei", "cage", "duns", "irs_number"]:
            if key in raw and raw[key]:
                identifiers[key] = raw[key]

    return identifiers


def extract_entity_mentions(enrichment_data: dict) -> list[dict]:
    """
    Extract entity mentions from enrichment findings.
    Returns list of {name, type, identifiers, country, source}.
    """
    mentions = []

    # Primary entity (the vendor being enriched)
    mentions.append({
        "name": enrichment_data.get("vendor_name", ""),
        "type": "company",  # Assume company unless indicated otherwise
        "identifiers": enrichment_data.get("identifiers", {}),
        "country": enrichment_data.get("country", ""),
        "source": "enrichment_primary",
    })

    # Parse relationships for secondary entities
    for rel in enrichment_data.get("relationships", []):
        if rel.get("type") == "subsidiary_of":
            mentions.append({
                "name": rel.get("target_name", ""),
                "type": "company",
                "identifiers": rel.get("target_identifiers", {}),
                "country": rel.get("target_country", ""),
                "source": f"{enrichment_data.get('_source', 'unknown')}:relationship",
            })
        elif rel.get("type") == "officer_of":
            officer_name = rel.get("officer_name", "") or rel.get("source_entity", "")
            mentions.append({
                "name": officer_name,
                "type": "person",
                "identifiers": rel.get("officer_ids", {}) or rel.get("source_identifiers", {}),
                "country": "",
                "source": f"{enrichment_data.get('_source', 'unknown')}:officer",
            })

    # Filter empty names
    mentions = [m for m in mentions if m.get("name", "").strip()]

    return mentions


# ---------------------------------------------------------------------------
# Entity Resolver
# ---------------------------------------------------------------------------

class EntityResolver:
    """
    Lightweight entity resolution engine.

    Matches entities by:
    1. Exact identifier match (deterministic, confidence 1.0)
    2. Fuzzy name match + country match (probabilistic, threshold 0.88-0.92)
    3. Creates relationships from enrichment data
    """

    def __init__(self):
        self.entities: dict[str, ResolvedEntity] = {}  # id -> entity
        self._name_index: dict[str, list[str]] = {}    # normalized_name -> entity_ids
        self._identifier_index: dict[str, str] = {}    # identifier_str -> entity_id

    def _add_to_indices(self, entity: ResolvedEntity) -> None:
        """Update internal indices for fast lookups."""
        # Name index
        norm_name = normalize_name(entity.canonical_name)
        if norm_name not in self._name_index:
            self._name_index[norm_name] = []
        if entity.id not in self._name_index[norm_name]:
            self._name_index[norm_name].append(entity.id)

        # Identifier index
        for id_type, id_val in entity.identifiers.items():
            if id_val:
                key = f"{id_type}:{id_val}".lower()
                self._identifier_index[key] = entity.id

    def find_by_identifier(self, id_type: str, id_val: str) -> Optional[str]:
        """Look up entity ID by identifier (CIK, LEI, UEI, CAGE)."""
        if not id_val:
            return None
        key = f"{id_type}:{id_val}".lower()
        return self._identifier_index.get(key)

    def find_by_fuzzy_name(self, name: str, country: str = "", threshold: float = 0.88) -> list[tuple[str, float]]:
        """
        Find entities by fuzzy name match.
        Returns list of (entity_id, score) tuples sorted by score.
        """
        if not name:
            return []

        norm_name = normalize_name(name)
        candidates = []

        # Scan all entities
        for entity_id, entity in self.entities.items():
            entity_norm = normalize_name(entity.canonical_name)
            score = jaro_winkler(norm_name, entity_norm)

            if score >= threshold:
                # Boost score if country matches
                if country and entity.country and entity.country.upper() == country.upper():
                    score = min(1.0, score + 0.05)
                candidates.append((entity_id, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def add_entity(
        self,
        name: str,
        entity_type: str,
        identifiers: dict,
        source: str,
        country: str = "",
        aliases: list = None,
    ) -> str:
        """
        Add or merge an entity into the graph.
        Returns the entity ID (new or existing).
        """
        if aliases is None:
            aliases = []

        # Check for existing match by identifier (exact)
        for id_type, id_val in identifiers.items():
            existing_id = self.find_by_identifier(id_type, id_val)
            if existing_id:
                # Merge into existing entity
                entity = self.entities[existing_id]
                if name and name not in entity.aliases:
                    entity.aliases.append(name)
                if source not in entity.sources:
                    entity.sources.append(source)
                if country and not entity.country:
                    entity.country = country
                # Update identifiers
                entity.identifiers.update(identifiers)
                entity.confidence = min(1.0, entity.confidence + 0.05)
                entity.last_updated = datetime.utcnow().isoformat() + "Z"
                self._add_to_indices(entity)
                return existing_id

        # Check for fuzzy match by name + country
        fuzzy_matches = self.find_by_fuzzy_name(name, country, threshold=0.88)
        if fuzzy_matches:
            best_id, best_score = fuzzy_matches[0]
            # High confidence match: merge
            if best_score >= 0.92:
                entity = self.entities[best_id]
                if name and name not in entity.aliases:
                    entity.aliases.append(name)
                if source not in entity.sources:
                    entity.sources.append(source)
                entity.identifiers.update(identifiers)
                entity.confidence = min(1.0, (entity.confidence + best_score) / 2)
                entity.last_updated = datetime.utcnow().isoformat() + "Z"
                self._add_to_indices(entity)
                return best_id
            # Possible match: could handle differently, but for now create new

        # Create new entity
        entity_id = generate_entity_id(name, identifiers)
        entity = ResolvedEntity(
            id=entity_id,
            canonical_name=name,
            entity_type=entity_type,
            aliases=aliases,
            identifiers=identifiers,
            country=country,
            sources=[source],
            confidence=1.0 if identifiers else 0.7,
            last_updated=datetime.utcnow().isoformat() + "Z",
        )

        self.entities[entity_id] = entity
        self._add_to_indices(entity)
        return entity_id

    def resolve(self, enrichment_report: dict) -> dict:
        """
        Process an enrichment report and resolve all entities.

        Returns:
            {
                "primary_entity_id": str,
                "entities": {entity_id: ResolvedEntity.to_dict()},
                "relationships": [{source_id, target_id, type, confidence, source}],
                "resolution_confidence": float,
            }
        """
        # Extract all entity mentions from the enrichment report
        mentions = extract_entity_mentions(enrichment_report)

        # Add primary entity first
        primary_entity_id = None
        for mention in mentions:
            if mention["source"] == "enrichment_primary":
                primary_entity_id = self.add_entity(
                    name=mention["name"],
                    entity_type=mention["type"],
                    identifiers=mention["identifiers"],
                    source=enrichment_report.get("source", "unknown"),
                    country=mention.get("country", ""),
                )
                break

        # Add secondary entities
        secondary_ids = []
        for mention in mentions:
            if mention["source"] != "enrichment_primary":
                entity_id = self.add_entity(
                    name=mention["name"],
                    entity_type=mention["type"],
                    identifiers=mention["identifiers"],
                    source=mention["source"],
                    country=mention.get("country", ""),
                )
                secondary_ids.append(entity_id)

        # Build relationships
        relationships = []
        for rel in enrichment_report.get("relationships", []):
            source_name = enrichment_report.get("vendor_name", "")
            target_name = rel.get("target_name", "")

            # Look up IDs
            source_id = self.find_by_identifier(
                rel.get("source_id_type", ""),
                rel.get("source_id", "")
            )
            if not source_id:
                source_id = self.find_by_fuzzy_name(source_name,
                                                   enrichment_report.get("country", ""))[0][0] \
                           if self.find_by_fuzzy_name(source_name) else None

            target_id = self.find_by_identifier(
                rel.get("target_id_type", ""),
                rel.get("target_id", "")
            )
            if not target_id:
                target_id = self.find_by_fuzzy_name(target_name,
                                                   rel.get("target_country", ""))[0][0] \
                           if self.find_by_fuzzy_name(target_name) else None

            if source_id and target_id:
                rel_dict = {
                    "source_entity_id": source_id,
                    "target_entity_id": target_id,
                    "rel_type": rel.get("type", "related"),
                    "confidence": rel.get("confidence", 0.7),
                    "data_source": enrichment_report.get("source", "unknown"),
                    "evidence": rel.get("evidence", ""),
                }
                relationships.append(rel_dict)

                # Store relationship in entities
                self.entities[source_id].relationships.append(rel_dict)

        # Compute overall resolution confidence
        avg_confidence = sum(e.confidence for e in self.entities.values()) / max(1, len(self.entities))

        return {
            "primary_entity_id": primary_entity_id,
            "entities": {eid: e.to_dict() for eid, e in self.entities.items()},
            "relationships": relationships,
            "resolution_confidence": avg_confidence,
        }

    def find_connections(self, entity_id: str, depth: int = 1) -> list[dict]:
        """
        Find all entities connected to a given entity (BFS).
        """
        if entity_id not in self.entities:
            return []

        visited = set()
        queue = [(entity_id, 0)]
        results = []

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_id in visited or current_depth > depth:
                continue
            visited.add(current_id)

            current_entity = self.entities.get(current_id)
            if not current_entity:
                continue

            for rel in current_entity.relationships:
                target_id = rel["target_entity_id"]
                results.append({
                    "source_entity_id": current_id,
                    "target_entity_id": target_id,
                    "rel_type": rel["rel_type"],
                    "confidence": rel["confidence"],
                    "depth": current_depth + 1,
                })

                if target_id not in visited and current_depth < depth:
                    queue.append((target_id, current_depth + 1))

        return results

    def get_entity(self, entity_id: str) -> Optional[ResolvedEntity]:
        """Retrieve an entity by ID."""
        return self.entities.get(entity_id)

    def to_graph_dict(self) -> dict:
        """Export the entity graph as a dict for API response."""
        return {
            "entity_count": len(self.entities),
            "entities": {eid: e.to_dict() for eid, e in self.entities.items()},
            "relationship_count": sum(len(e.relationships) for e in self.entities.values()),
            "exported_at": datetime.utcnow().isoformat() + "Z",
        }
