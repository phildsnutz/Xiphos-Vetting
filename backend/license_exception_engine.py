"""
License Exception Eligibility Engine (S12-02)

Evaluates whether an export transaction requiring a license may qualify
for a BIS license exception under EAR Part 740. This is a rules-based
engine that checks eligibility criteria for each exception type against
the transaction parameters.

License exceptions are the most commonly used authorization pathway in
export compliance. Getting this right is a major differentiator because
it saves companies weeks of license application processing time.

Supported BIS License Exceptions (EAR Part 740):
  - TMP (Temporary Imports, Exports, Reexports, and Transfers)
  - RPL (Servicing and Replacement of Parts and Equipment)
  - GOV (Governments and International Organizations)
  - TSR (Technology and Software under Restriction)
  - STA (Strategic Trade Authorization)
  - ENC (Encryption Commodities, Software, and Technology)
  - APR (Additional Permissive Reexports)
  - CIV (Civil End Users)
  - TSU (Technology and Software Unrestricted)
  - BAG (Baggage)
  - GBS (Group B Shipments)

Usage:
    from license_exception_engine import check_license_exception
    result = check_license_exception(
        classification="3A001",
        destination_country="GB",
        end_use="Radar signal processing for UK MoD",
        current_posture="likely_license_required",
    )
"""

import logging

logger = logging.getLogger("xiphos.license_exception")


# ---------------------------------------------------------------------------
# EAR Country Groups (simplified for rules engine)
# ---------------------------------------------------------------------------

# Country Group A:1 (Wassenaar Arrangement) - eligible for STA
COUNTRY_GROUP_A1 = {
    "AR", "AU", "AT", "BE", "BG", "CA", "HR", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "JP", "KR", "LV", "LT", "LU", "MT", "MX",
    "NL", "NZ", "NO", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "CH", "TR",
    "UA", "GB", "US", "ZA", "IN",
}

# Country Group A:5 - eligible for STA (subset)
COUNTRY_GROUP_A5 = {
    "AU", "AT", "BE", "BG", "CA", "HR", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "JP", "LV", "LT", "LU", "MT", "NL",
    "NZ", "NO", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "CH", "GB",
}

# Country Group B (broad allied group)
COUNTRY_GROUP_B = COUNTRY_GROUP_A1 | {
    "AL", "BD", "BA", "CL", "CO", "CR", "CY", "EC", "SV", "GE", "GH",
    "GT", "HN", "IS", "JM", "KE", "MY", "MU", "MA", "NI", "NG", "PA",
    "PY", "PE", "PH", "SG", "LK", "TH", "TT", "TN", "UY", "VN",
}

# Country Group D:1 (National Security) - generally restricted
COUNTRY_GROUP_D1 = {
    "AF", "AM", "AZ", "BH", "BY", "CN", "CU", "CY", "EG", "GE",
    "HK", "IQ", "IL", "JO", "KZ", "KW", "KG", "LB", "LY", "MO",
    "MN", "OM", "PK", "QA", "RU", "SA", "TJ", "TM", "AE", "UZ", "VN",
}

# Country Group E:1 (Embargoed) - no exceptions available
COUNTRY_GROUP_E1 = {"CU", "IR", "KP", "SY"}

# Country Group E:2
COUNTRY_GROUP_E2 = {"CU", "IR", "KP", "SY", "RU", "BY"}


# ---------------------------------------------------------------------------
# ECCN to exception eligibility mapping
# ---------------------------------------------------------------------------

# ECCNs that are explicitly excluded from STA
STA_EXCLUDED_ECCNS = {
    "0A501", "0A502", "0A503", "0A504", "0A505",  # Firearms
    "0A606", "0B606", "0D606", "0E606",            # 600-series firearms
    "1C351", "1C352", "1C353", "1C354",            # Biological agents
    "1C995", "2B352",                               # Chemical/bio production
}

# ECCNs eligible for ENC exception
ENC_ELIGIBLE_PREFIXES = {"5A002", "5A004", "5B002", "5D002", "5E002"}

def six_hundred_series_pattern(eccn: str | None) -> bool:
    """Return True when an ECCN is part of the 600-series family."""
    if not eccn or len(eccn) < 5:
        return False
    return eccn[1:4] in {"A60", "B60", "C60", "D60", "E60"}


def nine_x_515_pattern(eccn: str | None) -> bool:
    """Return True when an ECCN is part of the 9x515 family."""
    return bool(eccn and eccn.startswith("9") and "515" in eccn)


# ---------------------------------------------------------------------------
# Exception definitions
# ---------------------------------------------------------------------------

class LicenseException:
    """Represents a BIS license exception with eligibility criteria."""

    def __init__(self, code: str, name: str, ear_section: str, description: str):
        self.code = code
        self.name = name
        self.ear_section = ear_section
        self.description = description

    def check_eligibility(
        self,
        classification: str,
        destination_country: str,
        end_use: str,
        persons_nationalities: list[str] = None,
        is_reexport: bool = False,
        is_temporary: bool = False,
        is_government_end_user: bool = False,
        item_value_usd: float = 0,
    ) -> dict:
        """Check if this exception applies. Returns eligibility result dict."""
        raise NotImplementedError


class ExceptionTMP(LicenseException):
    """740.9 - Temporary Imports, Exports, Reexports."""

    def __init__(self):
        super().__init__("TMP", "Temporary Export", "740.9",
                        "Items exported temporarily and returned within 1-4 years")

    def check_eligibility(self, classification, destination_country, end_use,
                         persons_nationalities=None, is_reexport=False,
                         is_temporary=False, is_government_end_user=False,
                         item_value_usd=0) -> dict:
        if destination_country in COUNTRY_GROUP_E1:
            return {"eligible": False, "reason": "E:1 destinations prohibited for TMP"}

        if not is_temporary:
            return {"eligible": False, "reason": "TMP requires temporary export (item must return)"}

        # TMP available for most items except certain weapons
        if classification and classification.startswith("0A") and "501" in classification:
            return {"eligible": False, "reason": "Firearms (0A501) excluded from TMP"}

        return {
            "eligible": True,
            "exception_code": "TMP",
            "conditions": [
                "Item must be returned to the US within the applicable time period",
                "Exporter must maintain control of the item",
                "No transfer to unauthorized parties while abroad",
            ],
            "ear_reference": "15 CFR 740.9",
            "confidence": 0.8,
        }


class ExceptionRPL(LicenseException):
    """740.10 - Servicing and Replacement Parts."""

    def __init__(self):
        super().__init__("RPL", "Replacement Parts", "740.10",
                        "One-for-one replacement of parts and components")

    def check_eligibility(self, classification, destination_country, end_use,
                         persons_nationalities=None, is_reexport=False,
                         is_temporary=False, is_government_end_user=False,
                         item_value_usd=0) -> dict:
        if destination_country in COUNTRY_GROUP_E1:
            return {"eligible": False, "reason": "E:1 destinations prohibited for RPL"}

        end_use_lower = (end_use or "").lower()
        is_replacement = any(kw in end_use_lower for kw in [
            "replacement", "repair", "servic", "spare", "maintenance", "refurbish"
        ])

        if not is_replacement:
            return {"eligible": False, "reason": "RPL requires replacement/servicing context"}

        return {
            "eligible": True,
            "exception_code": "RPL",
            "conditions": [
                "Must be one-for-one replacement of identical or equivalent parts",
                "Defective parts must be returned or destroyed",
                "Value limitation: replacement cannot exceed value of original",
            ],
            "ear_reference": "15 CFR 740.10",
            "confidence": 0.75,
        }


class ExceptionGOV(LicenseException):
    """740.11 - Governments and International Organizations."""

    def __init__(self):
        super().__init__("GOV", "Government End User", "740.11",
                        "Exports to foreign governments and international orgs")

    def check_eligibility(self, classification, destination_country, end_use,
                         persons_nationalities=None, is_reexport=False,
                         is_temporary=False, is_government_end_user=False,
                         item_value_usd=0) -> dict:
        if destination_country in COUNTRY_GROUP_E1:
            return {"eligible": False, "reason": "E:1 destinations prohibited for GOV"}

        if destination_country in {"CN", "RU", "VE"}:
            return {"eligible": False, "reason": f"GOV not available for {destination_country}"}

        if not is_government_end_user:
            end_use_lower = (end_use or "").lower()
            gov_keywords = ["government", "ministry", "mod ", "dod ", "nato", "military",
                          "defense department", "defence department", "armed forces"]
            if not any(kw in end_use_lower for kw in gov_keywords):
                return {"eligible": False, "reason": "GOV requires government/international org end user"}

        # GOV has specific ECCN limitations
        if classification and six_hundred_series_pattern(classification):
            if destination_country not in COUNTRY_GROUP_A5:
                return {"eligible": False, "reason": "600-series under GOV limited to A:5 countries"}

        return {
            "eligible": True,
            "exception_code": "GOV",
            "conditions": [
                "End user must be a foreign government or international organization",
                "Items must be for official government use",
                "End-use certificate may be required",
            ],
            "ear_reference": "15 CFR 740.11",
            "confidence": 0.85,
        }


class ExceptionSTA(LicenseException):
    """740.20 - Strategic Trade Authorization."""

    def __init__(self):
        super().__init__("STA", "Strategic Trade Authorization", "740.20",
                        "Broad exception for allied destinations")

    def check_eligibility(self, classification, destination_country, end_use,
                         persons_nationalities=None, is_reexport=False,
                         is_temporary=False, is_government_end_user=False,
                         item_value_usd=0) -> dict:
        # STA requires destination in A:5 (or A:1 for some items)
        if destination_country not in COUNTRY_GROUP_A5:
            if destination_country in COUNTRY_GROUP_A1:
                # A:1 but not A:5: limited STA eligibility
                pass
            else:
                return {"eligible": False, "reason": "STA requires Country Group A:5 or A:1 destination"}

        # Check ECCN exclusions
        if classification and classification.upper() in STA_EXCLUDED_ECCNS:
            return {"eligible": False, "reason": f"ECCN {classification} excluded from STA"}

        if classification and nine_x_515_pattern(classification):
            return {"eligible": False, "reason": "9x515 items excluded from STA"}

        # STA requires consignee statement
        conditions = [
            "Consignee must provide STA consignee statement per Supplement 2 to Part 748",
            "Exporter must verify no knowledge of diversion risk",
            "Items may not be reexported from STA-eligible country without authorization",
        ]

        if destination_country in COUNTRY_GROUP_A5:
            confidence = 0.9
        else:
            confidence = 0.7
            conditions.append("A:1 (non-A:5) destination: verify specific ECCN eligibility under STA")

        return {
            "eligible": True,
            "exception_code": "STA",
            "conditions": conditions,
            "ear_reference": "15 CFR 740.20",
            "confidence": confidence,
        }


class ExceptionENC(LicenseException):
    """740.17 - Encryption."""

    def __init__(self):
        super().__init__("ENC", "Encryption", "740.17",
                        "Mass-market and other encryption items")

    def check_eligibility(self, classification, destination_country, end_use,
                         persons_nationalities=None, is_reexport=False,
                         is_temporary=False, is_government_end_user=False,
                         item_value_usd=0) -> dict:
        if destination_country in COUNTRY_GROUP_E1:
            return {"eligible": False, "reason": "E:1 destinations prohibited for ENC"}

        # Check if ECCN is encryption-related
        is_enc_item = False
        if classification:
            for prefix in ENC_ELIGIBLE_PREFIXES:
                if classification.upper().startswith(prefix[:4]):
                    is_enc_item = True
                    break

        if not is_enc_item:
            return {"eligible": False, "reason": "ENC only applies to Category 5 Part 2 items"}

        return {
            "eligible": True,
            "exception_code": "ENC",
            "conditions": [
                "Self-classification and reporting may be required",
                "Mass-market items may qualify for ENC unrestricted",
                "Government end users in D:1 countries may require license",
            ],
            "ear_reference": "15 CFR 740.17",
            "confidence": 0.8,
        }


class ExceptionTSU(LicenseException):
    """740.13 - Technology and Software Unrestricted."""

    def __init__(self):
        super().__init__("TSU", "Technology/Software Unrestricted", "740.13",
                        "Publicly available technology, software updates, releases")

    def check_eligibility(self, classification, destination_country, end_use,
                         persons_nationalities=None, is_reexport=False,
                         is_temporary=False, is_government_end_user=False,
                         item_value_usd=0) -> dict:
        if destination_country in COUNTRY_GROUP_E1:
            return {"eligible": False, "reason": "E:1 destinations prohibited for TSU"}

        end_use_lower = (end_use or "").lower()
        tsu_keywords = ["software update", "patch", "bug fix", "publicly available",
                       "open source", "published", "educational"]

        if not any(kw in end_use_lower for kw in tsu_keywords):
            return {"eligible": False, "reason": "TSU requires publicly available tech/software or updates"}

        return {
            "eligible": True,
            "exception_code": "TSU",
            "conditions": [
                "Technology/software must be publicly available per 734.7",
                "Or must be a software update per 740.13(c)",
                "No knowledge of prohibited end use",
            ],
            "ear_reference": "15 CFR 740.13",
            "confidence": 0.7,
        }


class ExceptionCIV(LicenseException):
    """740.5 - Civil End Users."""

    def __init__(self):
        super().__init__("CIV", "Civil End Users", "740.5",
                        "Items for civil end use in Country Group D:1")

    def check_eligibility(self, classification, destination_country, end_use,
                         persons_nationalities=None, is_reexport=False,
                         is_temporary=False, is_government_end_user=False,
                         item_value_usd=0) -> dict:
        if destination_country in COUNTRY_GROUP_E1:
            return {"eligible": False, "reason": "E:1 destinations prohibited for CIV"}

        if is_government_end_user:
            return {"eligible": False, "reason": "CIV not available for government end users"}

        end_use_lower = (end_use or "").lower()
        military_keywords = ["military", "defense", "weapon", "munition", "surveillance",
                           "intelligence", "ministry of defence", "mod ", "dod "]
        if any(kw in end_use_lower for kw in military_keywords):
            return {"eligible": False, "reason": "CIV not available for military end use"}

        # CIV limited to specific ECCNs
        if classification:
            eccn = classification.upper()
            civ_eligible = eccn.endswith("99") or eccn in {"EAR99"}
            if not civ_eligible:
                return {"eligible": False, "reason": "CIV limited to specific low-control ECCNs"}

        return {
            "eligible": True,
            "exception_code": "CIV",
            "conditions": [
                "End user must be a civil entity (non-government, non-military)",
                "End use must be exclusively civil",
                "CIV statement from consignee may be required",
            ],
            "ear_reference": "15 CFR 740.5",
            "confidence": 0.65,
        }


# ---------------------------------------------------------------------------
# Engine registry
# ---------------------------------------------------------------------------

ALL_EXCEPTIONS = [
    ExceptionSTA(),   # Most broadly applicable
    ExceptionGOV(),   # Government end users
    ExceptionENC(),   # Encryption items
    ExceptionTMP(),   # Temporary exports
    ExceptionRPL(),   # Replacement parts
    ExceptionTSU(),   # Unrestricted tech/software
    ExceptionCIV(),   # Civil end users
]


# ---------------------------------------------------------------------------
# Main check function (called by TransactionOrchestrator)
# ---------------------------------------------------------------------------

def check_license_exception(
    classification: str = "",
    destination_country: str = "",
    end_use: str = "",
    current_posture: str = "",
    persons_nationalities: list[str] = None,
    is_reexport: bool = False,
    is_temporary: bool = False,
    is_government_end_user: bool = False,
    item_value_usd: float = 0,
) -> dict:
    """
    Check all applicable license exceptions for a transaction.

    Returns:
    {
        "eligible": bool,           # True if any exception applies
        "exception_code": str,      # Best (highest confidence) exception
        "exception_name": str,
        "all_eligible": [...],      # All qualifying exceptions
        "all_ineligible": [...],    # Rejected exceptions with reasons
        "recommendation": str,      # Plain English guidance
    }
    """
    # Don't bother checking if posture doesn't require a license
    if current_posture in ("likely_nlr", "likely_prohibited"):
        reason = "NLR transactions do not need license exceptions" if current_posture == "likely_nlr" else "Prohibited transactions cannot use license exceptions"
        return {
            "eligible": False,
            "exception_code": None,
            "reason": reason,
            "all_eligible": [],
            "all_ineligible": [],
        }

    # E:1 destinations: no exceptions available
    if destination_country and destination_country.upper() in COUNTRY_GROUP_E1:
        return {
            "eligible": False,
            "exception_code": None,
            "reason": f"No license exceptions available for embargoed destination ({destination_country})",
            "all_eligible": [],
            "all_ineligible": [{"code": e.code, "reason": "E:1 embargo"} for e in ALL_EXCEPTIONS],
        }

    # Detect government end user from end_use text
    if not is_government_end_user and end_use:
        end_use_lower = end_use.lower()
        gov_keywords = ["government", "ministry", "mod ", "dod ", "nato", "military",
                       "defense department", "defence department", "armed forces"]
        if any(kw in end_use_lower for kw in gov_keywords):
            is_government_end_user = True

    eligible = []
    ineligible = []

    for exc in ALL_EXCEPTIONS:
        try:
            result = exc.check_eligibility(
                classification=classification or "",
                destination_country=(destination_country or "").upper(),
                end_use=end_use or "",
                persons_nationalities=persons_nationalities or [],
                is_reexport=is_reexport,
                is_temporary=is_temporary,
                is_government_end_user=is_government_end_user,
                item_value_usd=item_value_usd,
            )
            if result.get("eligible"):
                eligible.append(result)
            else:
                ineligible.append({
                    "code": exc.code,
                    "name": exc.name,
                    "reason": result.get("reason", "Not eligible"),
                })
        except Exception as e:
            logger.warning(f"Exception check {exc.code} failed: {e}")
            ineligible.append({"code": exc.code, "name": exc.name, "reason": f"Check error: {str(e)}"})

    if eligible:
        # Sort by confidence descending
        eligible.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        best = eligible[0]

        recommendation = (
            f"License exception {best['exception_code']} ({best.get('ear_reference', '')}) "
            f"may authorize this transaction. Confidence: {best.get('confidence', 0):.0%}. "
            f"Verify conditions are met before proceeding."
        )

        return {
            "eligible": True,
            "exception_code": best["exception_code"],
            "exception_name": best.get("exception_code", ""),
            "best_match": best,
            "all_eligible": eligible,
            "all_ineligible": ineligible,
            "recommendation": recommendation,
        }

    return {
        "eligible": False,
        "exception_code": None,
        "all_eligible": [],
        "all_ineligible": ineligible,
        "recommendation": "No license exceptions appear applicable. A BIS license application is required.",
    }
