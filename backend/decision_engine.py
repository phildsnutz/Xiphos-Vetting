"""
Xiphos Decision Engine: Alert Classification Module

Classifies screening alerts from ofac.py into disposition categories
that determine workflow routing and risk weight override for the
FGAMLogit scoring layer.

Per ACAMS/Wolfsberg guidance, adapted for defense vendor risk:
- DEFINITE: Auto-block, no human review
- PROBABLE: Escalate to compliance officer
- POSSIBLE: Queue for analyst review
- UNLIKELY: Auto-clear, log for audit trail

This module encodes compliance policy decisions that change at a
different cadence than matching algorithms. Synchronous, pure-function
design enables easy threshold adjustments without touching scoring math.
"""

from dataclasses import dataclass
from ofac import ScreeningResult


@dataclass
class AlertDisposition:
    """
    Classification result for a screening match.
    
    Maps a screening alert into a disposition category with:
    - Confidence band (HIGH/MEDIUM/LOW)
    - Recommended action for workflow routing
    - Override risk weight for fgamlogit.py
    - Full audit trail of classification factors
    """
    category: str              # DEFINITE, PROBABLE, POSSIBLE, UNLIKELY
    confidence_band: str       # HIGH, MEDIUM, LOW
    recommended_action: str    # BLOCK, ESCALATE, REVIEW, AUTO_CLEAR
    override_risk_weight: float  # 0.0 - 1.0, replaces raw composite in fgamlogit
    screening_result: ScreeningResult  # Original screening output
    classification_factors: dict  # What drove the classification
    explanation: str           # Human-readable justification


# Adversary nations per OFAC/EO designations
ADVERSARY_NATIONS = {"RU", "CN", "IR", "KP", "SY", "CU", "BY", "VE", "MM"}


def classify_alert(screening_result: ScreeningResult, vendor_country: str = "") -> AlertDisposition:
    """
    Classify a screening result into a disposition category.
    
    Implements 4-tier classification based on composite score, token overlap,
    and country metadata confirmation.
    
    Args:
        screening_result: ScreeningResult from ofac.screen_name()
        vendor_country: Optional ISO country code for the vendor.
            Enables country-mismatch detection to suppress false positives.
    
    Returns:
        AlertDisposition with category, action, and risk weight override.
    """
    
    # If not matched, immediately return UNLIKELY
    if not screening_result.matched or screening_result.matched_entry is None:
        return AlertDisposition(
            category="UNLIKELY",
            confidence_band="LOW",
            recommended_action="AUTO_CLEAR",
            override_risk_weight=0.0,
            screening_result=screening_result,
            classification_factors={
                "matched": False,
                "reason": "No match in screening database"
            },
            explanation="Screening result did not match any sanctions entry. No further action required."
        )
    
    best_score = screening_result.best_score
    matched_entry = screening_result.matched_entry
    match_details = screening_result.match_details
    
    # Extract key signals from match_details
    # ofac.py uses "token_containment" (float) and "distinctive_tokens" (int count)
    token_containment = match_details.get("token_containment", match_details.get("sig_containment", 0.0))
    distinctive_tokens_raw = match_details.get("distinctive_tokens", 0)
    distinctive_tokens_count = distinctive_tokens_raw if isinstance(distinctive_tokens_raw, int) else len(distinctive_tokens_raw)
    idf_token_score = match_details.get("idf_token_score", match_details.get("idf_token", 0.0))
    
    # Check if entry is from fallback watchlist (uid starts with "XIPHOS-FB-")
    is_fallback_match = matched_entry.uid.startswith("XIPHOS-FB-")
    
    # Check for country mismatch
    has_country_mismatch = (
        vendor_country and
        vendor_country != matched_entry.country
    )
    
    is_adversary_country = matched_entry.country in ADVERSARY_NATIONS
    
    # Build classification_factors for audit trail
    factors = {
        "composite_score": best_score,
        "matched_entry_uid": matched_entry.uid,
        "matched_entry_country": matched_entry.country,
        "vendor_country": vendor_country,
        "is_fallback_match": is_fallback_match,
        "token_containment": token_containment,
        "distinctive_tokens_count": distinctive_tokens_count,
        "idf_token_score": idf_token_score,
        "country_mismatch": has_country_mismatch,
        "adversary_country": is_adversary_country,
    }
    
    # --- DEFINITE Classification (weight=1.0, confidence=HIGH) ---
    # Composite score >= 0.95
    # OR exact name match on fallback watchlist (uid starts with "XIPHOS-FB-")
    # OR token containment >= 1.0 AND IDF token score >= 0.8
    if (best_score >= 0.95 or
        is_fallback_match or
        (token_containment >= 1.0 and idf_token_score >= 0.8)):
        
        explanation_parts = []
        if best_score >= 0.95:
            explanation_parts.append(f"Composite score {best_score:.2f} >= 0.95 (very high confidence match)")
        if is_fallback_match:
            explanation_parts.append(f"Exact match on fallback watchlist (UID: {matched_entry.uid})")
        if token_containment >= 1.0 and idf_token_score >= 0.8:
            explanation_parts.append(f"Complete token containment (1.0) with high IDF score ({idf_token_score:.2f})")
        
        return AlertDisposition(
            category="DEFINITE",
            confidence_band="HIGH",
            recommended_action="BLOCK",
            override_risk_weight=1.0,
            screening_result=screening_result,
            classification_factors=factors,
            explanation=" | ".join(explanation_parts) + ". AUTO-BLOCK: No human review needed."
        )
    
    # --- PROBABLE Classification (weight=0.85, confidence=MEDIUM) ---
    # Composite score 0.85-0.94
    # AND at least 2 distinctive shared tokens
    # AND no country mismatch (or country is adversary nation)
    if (0.85 <= best_score <= 0.94 and
        distinctive_tokens_count >= 2 and
        (not has_country_mismatch or is_adversary_country)):
        
        explanation_parts = [
            f"Composite score {best_score:.2f} in 0.85-0.94 range (strong match)",
            f"{distinctive_tokens_count} distinctive shared tokens"
        ]
        if is_adversary_country:
            explanation_parts.append(f"Matched entry from adversary nation: {matched_entry.country}")
        
        return AlertDisposition(
            category="PROBABLE",
            confidence_band="MEDIUM",
            recommended_action="ESCALATE",
            override_risk_weight=0.85,
            screening_result=screening_result,
            classification_factors=factors,
            explanation=" | ".join(explanation_parts) + ". ESCALATE to compliance officer for review."
        )
    
    # --- POSSIBLE Classification (weight=0.60, confidence=LOW) ---
    # Composite score 0.75-0.84
    # OR composite 0.85+ with country mismatch or low distinctive tokens
    if (0.75 <= best_score <= 0.84 or
        (best_score >= 0.85 and (has_country_mismatch or distinctive_tokens_count < 2))):
        
        explanation_parts = [
            f"Composite score {best_score:.2f}"
        ]
        if 0.75 <= best_score <= 0.84:
            explanation_parts.append("in 0.75-0.84 range (moderate match)")
        if best_score >= 0.85 and has_country_mismatch and not is_adversary_country:
            explanation_parts.append(f"Country mismatch: matched entry is {matched_entry.country}, vendor is {vendor_country}")
        if distinctive_tokens_count < 2:
            explanation_parts.append(f"Low distinctive tokens ({distinctive_tokens_count} < 2)")
        
        return AlertDisposition(
            category="POSSIBLE",
            confidence_band="LOW",
            recommended_action="REVIEW",
            override_risk_weight=0.60,
            screening_result=screening_result,
            classification_factors=factors,
            explanation=" | ".join(explanation_parts) + ". REVIEW: Queue for analyst examination."
        )
    
    # --- UNLIKELY Classification (weight=0.0, confidence=LOW) ---
    # Composite score < 0.75
    return AlertDisposition(
        category="UNLIKELY",
        confidence_band="LOW",
        recommended_action="AUTO_CLEAR",
        override_risk_weight=0.0,
        screening_result=screening_result,
        classification_factors=factors,
        explanation=f"Composite score {best_score:.2f} < 0.75 (below threshold). AUTO-CLEAR: No further action needed."
    )
