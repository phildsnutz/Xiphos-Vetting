"""
Compatibility shim over the canonical profile registry in `profiles.py`.

The runtime now treats `backend/profiles.py` as the single source of truth.
This module preserves the legacy enum-based API used by FGAMLogit and the
standalone screening API.
"""

from __future__ import annotations

from enum import Enum

from profiles import (
    PROFILE_ENUM_TO_ID,
    PROFILE_ID_TO_ENUM_NAME,
    ComplianceProfile as ProfileConfig,
    get_connector_list,
    get_profile as get_profile_by_id,
    list_profiles as list_canonical_profiles,
    normalize_profile_id,
)


class ComplianceProfile(str, Enum):
    """Legacy enum surface retained for callers that still use enum values."""

    DEFENSE_ACQUISITION = "DEFENSE_ACQUISITION"
    ITAR_TRADE = "ITAR_TRADE"
    UNIVERSITY_RESEARCH = "UNIVERSITY_RESEARCH"
    GRANTS_COMPLIANCE = "GRANTS_COMPLIANCE"
    COMMERCIAL_SUPPLY_CHAIN = "COMMERCIAL_SUPPLY_CHAIN"

    @property
    def profile_id(self) -> str:
        return PROFILE_ENUM_TO_ID[self.value]

    @classmethod
    def _missing_(cls, value):
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return cls.DEFENSE_ACQUISITION

        upper = raw.upper()
        if upper in cls.__members__:
            return cls[upper]

        normalized_id = normalize_profile_id(raw)
        enum_name = PROFILE_ID_TO_ENUM_NAME.get(normalized_id)
        if enum_name:
            return cls[enum_name]
        return None


def coerce_profile(profile: ComplianceProfile | str | None) -> ComplianceProfile:
    """Accept enum values, canonical ids, or legacy strings."""
    if isinstance(profile, ComplianceProfile):
        return profile
    if profile is None:
        return ComplianceProfile.DEFENSE_ACQUISITION
    return ComplianceProfile(str(profile))


def get_profile(profile: ComplianceProfile | str) -> ProfileConfig:
    """Return the canonical profile config for an enum value or profile id."""
    enum_profile = coerce_profile(profile)
    config = get_profile_by_id(enum_profile.profile_id)
    if not config:
        raise KeyError(f"Profile not registered: {profile}")
    return config


def get_active_gates(profile: ComplianceProfile | str) -> list[str]:
    return list(get_profile(profile).enabled_gates)


def apply_weight_overrides(
    base_weights: dict[str, float],
    profile: ComplianceProfile | str,
) -> dict[str, float]:
    config = get_profile(profile)
    result = base_weights.copy()
    for factor, multiplier in config.weight_overrides.items():
        if factor in result:
            result[factor] = result[factor] * multiplier
    return result


def get_ui_labels(profile: ComplianceProfile | str) -> dict[str, str]:
    return dict(get_profile(profile).ui_labels)


def get_baseline_shift(profile: ComplianceProfile | str) -> float:
    return float(get_profile(profile).baseline_shift)


def get_priority_connectors(profile: ComplianceProfile | str) -> list[str]:
    config = get_profile(profile)
    connector_list = get_connector_list(config.id)
    return connector_list if connector_list is not None else list(config.connector_priority)


def get_hard_stops(profile: ComplianceProfile | str) -> list[str]:
    return list(get_profile(profile).additional_hard_stops)


def get_sensitivity_default(profile: ComplianceProfile | str) -> str:
    return str(get_profile(profile).sensitivity_default)


def list_profiles() -> list[tuple[ComplianceProfile, str, str]]:
    return [
        (ComplianceProfile(profile.enum_name), profile.name, profile.description)
        for profile in list_canonical_profiles()
    ]


def get_profile_info(profile: ComplianceProfile | str) -> dict:
    config = get_profile(profile)
    return {
        "name": config.enum_name,
        "profile_id": config.id,
        "display_name": config.name,
        "description": config.description,
        "gates": list(config.enabled_gates),
        "connectors": get_priority_connectors(profile),
        "sensitivity_default": config.sensitivity_default,
        "baseline_shift": config.baseline_shift,
        "weight_overrides": dict(config.weight_overrides),
        "ui_labels": dict(config.ui_labels),
        "hard_stops": list(config.additional_hard_stops),
    }
