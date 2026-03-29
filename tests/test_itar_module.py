"""
Test Suite for Xiphos ITAR Compliance Module
Tests comprehensive ITAR compliance assessment per 22 CFR 120-130

Test Coverage:
  1. USML Categories - All 21 categories present with correct risk levels
  2. Country Restrictions - Prohibited/elevated scrutiny/allowed logic
  3. Deemed Export Risk - Foreign national access assessment
  4. Red Flags - Transaction pattern indicators
  5. Integration - Full ITAR compliance pipeline
  6. DDTC Debarred List - Entity screening fallback

Model version: 1.0-TestITARCompliance
Date: March 2026
"""

import pytest
from backend.itar_module import (
    USMLCategory,
    USML_CATEGORIES,
    ITAR_PROHIBITED_COUNTRIES,
    ITAR_ELEVATED_SCRUTINY,
    CANADIAN_EXEMPTION_ELIGIBLE,
    ALLIED_NATIONS,
    assess_deemed_export_risk,
    check_red_flags,
    evaluate_itar_compliance,
    check_ddtc_debarred,
    DDTC_DEBARRED_FALLBACK,
)


# =============================================================================
# TEST SUITE 1: USML CATEGORIES
# =============================================================================

class TestUSMLCategories:
    """Verify USML category definitions per 22 CFR 121."""
    
    def test_all_21_categories_present(self):
        """Test that all 21 USML categories I-XXI are defined."""
        assert len(USML_CATEGORIES) == 21
        assert all(i in USML_CATEGORIES for i in range(1, 22))
    
    def test_category_dataclass_structure(self):
        """Test that each category has required attributes."""
        for category_num, category in USML_CATEGORIES.items():
            assert isinstance(category, USMLCategory)
            assert category.number == category_num
            assert category.name
            assert category.description
            assert category.risk_level in ("CRITICAL", "HIGH", "MEDIUM")
            assert 0.0 <= category.base_risk_weight <= 1.0
            assert isinstance(category.congressional_notification, bool)
            assert category.deemed_export_sensitivity in ("HIGH", "MEDIUM", "LOW")
            assert isinstance(category.examples, list)
            assert len(category.examples) > 0
    
    def test_critical_categories(self):
        """Test CRITICAL risk level categories (I-VII, IX, XVII-XX)."""
        critical_cats = {1, 2, 3, 4, 5, 6, 7, 9, 17, 18, 19, 20}
        for cat_num in critical_cats:
            assert USML_CATEGORIES[cat_num].risk_level == "CRITICAL"
            assert USML_CATEGORIES[cat_num].base_risk_weight >= 0.90
            assert USML_CATEGORIES[cat_num].congressional_notification is True
    
    def test_high_categories(self):
        """Test HIGH risk level categories (VIII, X-XIII, XVI)."""
        high_cats = {8, 10, 11, 12, 13, 16}
        for cat_num in high_cats:
            assert USML_CATEGORIES[cat_num].risk_level == "HIGH"
            assert 0.70 <= USML_CATEGORIES[cat_num].base_risk_weight <= 0.85
    
    def test_medium_categories(self):
        """Test MEDIUM risk level categories (XIV, XV, XXI)."""
        medium_cats = {14, 15, 21}
        for cat_num in medium_cats:
            assert USML_CATEGORIES[cat_num].risk_level == "MEDIUM"
            assert 0.50 <= USML_CATEGORIES[cat_num].base_risk_weight <= 0.65
    
    def test_usml_category_references(self):
        """Test that categories reference real ITAR items."""
        # Category 1: Firearms
        assert any("gun" in ex.lower() or "rifle" in ex.lower() 
                   for ex in USML_CATEGORIES[1].examples)
        # Category 7: Aircraft/Military aircraft
        assert any("jet" in ex.lower() or "helicopter" in ex.lower() or "drone" in ex.lower()
                   for ex in USML_CATEGORIES[7].examples)
        # Category 18: Technical data
        assert any("blueprint" in ex.lower() or "specification" in ex.lower() 
                   for ex in USML_CATEGORIES[18].examples)


# =============================================================================
# TEST SUITE 2: COUNTRY RESTRICTIONS
# =============================================================================

class TestCountryRestrictions:
    """Verify country restriction logic per 22 CFR 126.1."""
    
    def test_prohibited_countries_defined(self):
        """Test that prohibited countries per 22 CFR 126.1 are in set."""
        # Cuba, Iran, North Korea, Syria, Belarus, Russia
        assert "CU" in ITAR_PROHIBITED_COUNTRIES  # Cuba
        assert "IR" in ITAR_PROHIBITED_COUNTRIES  # Iran
        assert "KP" in ITAR_PROHIBITED_COUNTRIES  # North Korea
        assert "SY" in ITAR_PROHIBITED_COUNTRIES  # Syria
        assert "BY" in ITAR_PROHIBITED_COUNTRIES  # Belarus
        assert "RU" in ITAR_PROHIBITED_COUNTRIES  # Russia
        assert len(ITAR_PROHIBITED_COUNTRIES) == 6
    
    def test_elevated_scrutiny_countries(self):
        """Test that elevated scrutiny countries are defined."""
        # China, Venezuela, Myanmar, Sudan, Yemen, etc.
        assert "CN" in ITAR_ELEVATED_SCRUTINY  # China
        assert "VE" in ITAR_ELEVATED_SCRUTINY  # Venezuela
        assert "MM" in ITAR_ELEVATED_SCRUTINY  # Myanmar
        assert len(ITAR_ELEVATED_SCRUTINY) >= 10
    
    def test_canadian_exemption(self):
        """Test that Canadian exemption is available per 22 CFR 126.5."""
        assert "CA" in CANADIAN_EXEMPTION_ELIGIBLE
    
    def test_allied_nations(self):
        """Test that NATO/FIVE EYES nations are defined as allied."""
        # NATO and FIVE EYES countries
        assert "GB" in ALLIED_NATIONS  # United Kingdom
        assert "AU" in ALLIED_NATIONS  # Australia
        assert "CA" in ALLIED_NATIONS  # Canada
        assert "DE" in ALLIED_NATIONS  # Germany
        assert "FR" in ALLIED_NATIONS  # France
        assert "JP" in ALLIED_NATIONS  # Japan
        assert len(ALLIED_NATIONS) >= 12
    
    def test_country_sets_non_overlapping(self):
        """Test that prohibited countries don't overlap with other categories."""
        assert not (ITAR_PROHIBITED_COUNTRIES & ALLIED_NATIONS)
        assert not (ITAR_PROHIBITED_COUNTRIES & CANADIAN_EXEMPTION_ELIGIBLE)


# =============================================================================
# TEST SUITE 3: DEEMED EXPORT RISK ASSESSMENT
# =============================================================================

class TestDeemedExportRisk:
    """Verify deemed export risk assessment per 22 CFR 120.17."""
    
    def test_no_foreign_nationals_zero_risk(self):
        """Test that no foreign nationals = zero deemed export risk."""
        result = assess_deemed_export_risk(
            foreign_nationals=[],
            tcp_status="NOT_REQUIRED",
            usml_category=0,
        )
        assert result.risk_score == 0.0
        assert result.foreign_national_count == 0
        assert result.recommendation == "ALLOW"
    
    def test_prohibited_country_national_blocks(self):
        """Test that foreign nationals from prohibited countries = block."""
        result = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "IR", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="IMPLEMENTED",
            usml_category=7,  # Aircraft
        )
        assert result.risk_score == 1.0
        assert result.recommendation == "BLOCK"
        assert any("prohibited" in factor.lower() for factor in result.risk_factors)
    
    def test_elevated_scrutiny_without_tcp_high_risk(self):
        """Test elevated scrutiny country + no TCP = high risk/block."""
        result = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "CN", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="MISSING",
            usml_category=7,
        )
        # Elevated scrutiny (0.75) + HIGH sensitivity (*1.0) + missing TCP (+0.30) = 1.05 -> 1.0
        assert result.risk_score >= 0.75
        assert result.recommendation in ("BLOCK", "REQUIRE_LICENSE")
    
    def test_allied_nation_with_tcp_low_risk(self):
        """Test allied nation + TCP implemented = low risk."""
        result = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "GB", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="IMPLEMENTED",
            usml_category=7,
        )
        assert result.risk_score < 0.30
        assert result.recommendation == "ALLOW"
    
    def test_tcp_missing_penalty(self):
        """Test that missing TCP adds +0.30 risk penalty."""
        # With TCP implemented
        result_with_tcp = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "DE", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="IMPLEMENTED",
            usml_category=11,  # Military electronics
        )
        
        # Without TCP
        result_without_tcp = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "DE", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="MISSING",
            usml_category=11,
        )
        
        # Difference should be approximately +0.30
        assert result_without_tcp.risk_score - result_with_tcp.risk_score >= 0.25
    
    def test_usml_category_scaling(self):
        """Test that USML category sensitivity scales risk."""
        # Category 7 (Aircraft) - HIGH sensitivity
        result_high_sensitivity = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "PK", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="IMPLEMENTED",
            usml_category=7,
        )
        
        # Category 14 (Auxiliary equipment) - MEDIUM sensitivity
        result_medium_sensitivity = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "PK", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="IMPLEMENTED",
            usml_category=14,
        )
        
        # HIGH sensitivity should have higher risk
        assert result_high_sensitivity.risk_score >= result_medium_sensitivity.risk_score
    
    def test_multiple_foreign_nationals(self):
        """Test risk scales with number of foreign nationals from elevated scrutiny countries."""
        # Use elevated scrutiny country (CN) so we can see impact of foreign national count
        result_single = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "CN", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="IMPLEMENTED",
            usml_category=11,
        )
        
        result_many = assess_deemed_export_risk(
            foreign_nationals=[
                {"nationality": "CN", "role": "engineer", "access_level": "technical_data"}
                for _ in range(15)
            ],
            tcp_status="IMPLEMENTED",
            usml_category=11,
        )
        
        assert result_many.risk_score > result_single.risk_score


# =============================================================================
# TEST SUITE 4: RED FLAG ASSESSMENT
# =============================================================================

class TestRedFlagAssessment:
    """Verify red flag analysis per BIS/DDTC guidance."""
    
    def test_no_flags_zero_risk(self):
        """Test that clean transaction = no flags, low risk."""
        result = check_red_flags(
            transaction={
                "routing": ["US", "GB"],
                "customer_reluctance_on_end_use": False,
                "payment_method": "wire",
                "order_quantity": 100,
                "customer_prior_orders": True,
                "end_use_stated": "Commercial aircraft component assembly",
                "packaging_description": "Standard commercial packaging",
                "delivery_to_freight_forwarder": False,
                "declined_installation_training": False,
                "end_user_description_clarity": "detailed",
                "intermediate_consignee_country": "GB",
            },
            vendor_country="US",
            end_user_country="GB",
            usml_category=0,
        )
        assert result.score < 0.2
        assert len(result.flags_triggered) == 0
        assert result.recommendation == "ALLOW"
    
    def test_routing_through_diversion_hub(self):
        """Test that routing through known diversion hubs triggers flag."""
        result = check_red_flags(
            transaction={"routing": ["US", "AE", "GB"]},
            vendor_country="US",
            end_user_country="GB",
        )
        assert "unusual_routing" in result.flags_triggered
    
    def test_reluctant_end_use_info_triggers(self):
        """Test that customer reluctance on end-use triggers flag."""
        result = check_red_flags(
            transaction={"customer_reluctance_on_end_use": True},
            vendor_country="US",
            end_user_country="GB",
        )
        assert "reluctant_end_use_info" in result.flags_triggered
    
    def test_cash_payment_triggers(self):
        """Test that cash payment demand triggers flag."""
        result = check_red_flags(
            transaction={"payment_method": "cash"},
            vendor_country="US",
            end_user_country="GB",
        )
        assert "cash_payment_insistence" in result.flags_triggered
    
    def test_disproportionate_order_triggers(self):
        """Test that unusually large order triggers flag."""
        result = check_red_flags(
            transaction={"order_quantity": 5000},
            vendor_country="US",
            end_user_country="GB",
        )
        assert "disproportionate_order" in result.flags_triggered
    
    def test_new_customer_sensitive_item_triggers(self):
        """Test new customer + CRITICAL USML category triggers flag."""
        result = check_red_flags(
            transaction={"customer_prior_orders": False},
            vendor_country="US",
            end_user_country="CN",
            usml_category=3,  # Ordnance (CRITICAL)
        )
        assert "new_customer_sensitive_item" in result.flags_triggered
    
    def test_military_end_use_triggers(self):
        """Test that military end-use language triggers flag."""
        result = check_red_flags(
            transaction={"end_use_stated": "Military combat operations support"},
            vendor_country="US",
            end_user_country="GB",
        )
        assert "military_end_use_indicators" in result.flags_triggered
    
    def test_known_diversion_route(self):
        """Test that known diversion routes trigger flag."""
        result = check_red_flags(
            transaction={},
            vendor_country="US",
            end_user_country="IR",  # Prohibited destination
        )
        assert "known_diversion_route" in result.flags_triggered
    
    def test_declined_installation_triggers(self):
        """Test that declined installation/training triggers flag."""
        result = check_red_flags(
            transaction={"declined_installation_training": True},
            vendor_country="US",
            end_user_country="GB",
        )
        assert "declined_installation" in result.flags_triggered
    
    def test_vague_end_user_description_triggers(self):
        """Test that vague end-user description triggers flag."""
        result = check_red_flags(
            transaction={"end_user_description_clarity": "vague"},
            vendor_country="US",
            end_user_country="GB",
        )
        assert "vague_end_user_description" in result.flags_triggered
    
    def test_multiple_flags_scale_score(self):
        """Test that score increases with number of flags."""
        result_one_flag = check_red_flags(
            transaction={"payment_method": "cash"},
            vendor_country="US",
            end_user_country="GB",
        )
        
        result_multiple_flags = check_red_flags(
            transaction={
                "payment_method": "cash",
                "customer_reluctance_on_end_use": True,
                "routing": ["US", "AE", "GB"],
                "order_quantity": 2000,
                "declined_installation_training": True,
            },
            vendor_country="US",
            end_user_country="GB",
        )
        
        assert result_multiple_flags.score > result_one_flag.score


# =============================================================================
# TEST SUITE 5: INTEGRATED ITAR COMPLIANCE EVALUATION
# =============================================================================

class TestITARComplianceEvaluation:
    """Verify full ITAR compliance assessment pipeline."""
    
    def test_prohibited_country_vendor_blocked(self):
        """Test vendor in prohibited country = PROHIBITED overall status."""
        result = evaluate_itar_compliance(
            vendor_name="Iranian Defense Corp",
            vendor_country="IR",
            usml_category=7,
            ddtc_registered=False,
        )
        assert result.overall_status == "PROHIBITED"
        assert result.country_status == "PROHIBITED"
    
    def test_unregistered_itar_vendor_non_compliant(self):
        """Test unregistered vendor + ITAR item = NON_COMPLIANT."""
        result = evaluate_itar_compliance(
            vendor_name="Unregistered Defense Corp",
            vendor_country="US",
            usml_category=3,  # Ordnance (ITAR-controlled)
            ddtc_registered=False,
        )
        assert result.overall_status == "NON_COMPLIANT"
        assert result.registration_status == "UNREGISTERED"
    
    def test_clean_us_vendor_compliant(self):
        """Test U.S. vendor, DDTC registered, no ITAR item = COMPLIANT."""
        result = evaluate_itar_compliance(
            vendor_name="Acme Electronics Corp",
            vendor_country="US",
            usml_category=0,  # Not ITAR-controlled
            ddtc_registered=True,
        )
        assert result.overall_status == "COMPLIANT"
    
    def test_elevated_scrutiny_requires_review(self):
        """Test elevated scrutiny country = REQUIRES_REVIEW."""
        result = evaluate_itar_compliance(
            vendor_name="Beijing Tech Corp",
            vendor_country="CN",
            usml_category=11,
            ddtc_registered=True,
        )
        assert result.overall_status == "REQUIRES_REVIEW"
        assert result.country_status == "ELEVATED_SCRUTINY"
    
    def test_deemed_export_risk_escalates_status(self):
        """Test deemed export risk escalates compliance status."""
        result = evaluate_itar_compliance(
            vendor_name="Defense Tech Solutions",
            vendor_country="US",
            usml_category=7,
            ddtc_registered=True,
            foreign_nationals=[
                {"nationality": "CN", "role": "engineer", "access_level": "technical_data"},
            ],
            tcp_status="MISSING",
        )
        assert result.overall_status == "REQUIRES_REVIEW"
        assert result.deemed_export_risk.risk_score >= 0.50
    
    def test_red_flags_escalate_status(self):
        """Test red flags escalate compliance status."""
        result = evaluate_itar_compliance(
            vendor_name="Defense Corp",
            vendor_country="US",
            usml_category=3,
            ddtc_registered=True,
            transaction_flags={
                "payment_method": "cash",
                "customer_reluctance_on_end_use": True,
                "routing": ["US", "AE", "IR"],
                "order_quantity": 5000,
            },
            end_user_country="IR",
        )
        assert result.overall_status == "NON_COMPLIANT"
        assert len(result.red_flag_assessment.flags_triggered) >= 2
    
    def test_itar_item_requires_license(self):
        """Test ITAR item requires export license."""
        result = evaluate_itar_compliance(
            vendor_name="Aerospace Corp",
            vendor_country="US",
            usml_category=7,  # Aircraft
            ddtc_registered=True,
        )
        assert result.required_license_type == "DSP_5"
    
    def test_non_itar_item_no_license_required(self):
        """Test non-ITAR item requires no export license."""
        result = evaluate_itar_compliance(
            vendor_name="Electronics Corp",
            vendor_country="US",
            usml_category=0,
        )
        assert result.required_license_type == "NONE"
    
    def test_result_explanation_populated(self):
        """Test that explanation is provided in result."""
        result = evaluate_itar_compliance(
            vendor_name="Test Corp",
            vendor_country="US",
            usml_category=7,
            ddtc_registered=True,
        )
        assert result.explanation
        assert len(result.explanation) > 10
    
    def test_result_factors_dict_populated(self):
        """Test that factors dict contains all relevant info."""
        result = evaluate_itar_compliance(
            vendor_name="Test Corp",
            vendor_country="US",
            usml_category=7,
            ddtc_registered=True,
        )
        assert "vendor_name" in result.factors
        assert "vendor_country" in result.factors
        assert "usml_category" in result.factors
        assert "registration_status" in result.factors


# =============================================================================
# TEST SUITE 6: DDTC DEBARRED LIST
# =============================================================================

class TestDDTCDebarredList:
    """Verify DDTC debarred entity screening."""
    
    def test_debarred_list_populated(self):
        """Test that DDTC debarred fallback list has entries."""
        assert len(DDTC_DEBARRED_FALLBACK) >= 5
        for entity in DDTC_DEBARRED_FALLBACK:
            assert "name" in entity
            assert "date" in entity
            assert "basis" in entity
    
    def test_find_known_debarred_entity(self):
        """Test finding Raytheon in debarred list."""
        result = check_ddtc_debarred("Raytheon Technologies Corporation")
        assert result is not None
        assert "Raytheon" in result["name"]
        assert result["original_penalty"] > 0
    
    def test_find_debarred_by_dba(self):
        """Test finding entity by DBA name."""
        result = check_ddtc_debarred("FLIR")
        assert result is not None
        assert "FLIR" in result["name"]
    
    def test_unknown_entity_returns_none(self):
        """Test that unknown entity returns None."""
        result = check_ddtc_debarred("Unknown Random Corp")
        assert result is None
    
    def test_case_insensitive_search(self):
        """Test that debarred list search is case-insensitive."""
        result_upper = check_ddtc_debarred("HONEYWELL INTERNATIONAL INC")
        result_lower = check_ddtc_debarred("honeywell international inc")
        assert result_upper is not None
        assert result_lower is not None
        assert result_upper["name"] == result_lower["name"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
