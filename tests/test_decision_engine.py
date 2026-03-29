"""
Tests for the Decision Engine alert classification module.

Covers all 4 disposition categories, edge cases, and audit trail
validation for compliance routing decisions.
"""

import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import unittest
from decision_engine import classify_alert, ADVERSARY_NATIONS
from ofac import ScreeningResult, SanctionEntry


class TestDecisionEngine(unittest.TestCase):
    """Test suite for alert disposition classification."""
    
    def create_mock_screening_result(
        self,
        matched: bool,
        best_score: float,
        matched_entry: SanctionEntry = None,
        match_details: dict = None,
        vendor_name: str = "Test Vendor"
    ) -> ScreeningResult:
        """Helper to create mock ScreeningResult objects."""
        if match_details is None:
            match_details = {
                "sig_containment": 0.0,
                "distinctive_tokens": [],
                "idf_token_score": 0.0,
            }
        
        result = ScreeningResult(
            matched=matched,
            best_score=best_score,
            best_raw_jw=best_score,
            matched_entry=matched_entry,
            matched_name=vendor_name if matched_entry else "",
            match_details=match_details,
            all_matches=[],
            db_label="test",
            screening_ms=0
        )
        return result
    
    # =========================================================================
    # DEFINITE Classification Tests
    # =========================================================================
    
    def test_definite_high_composite_score(self):
        """DEFINITE: Composite score >= 0.95 returns BLOCK action."""
        entry = SanctionEntry(
            name="ROSOBORONEXPORT",
            aliases=["ROSOBORON"],
            program="UKRAINE-EO13661",
            list_type="SSI",
            country="RU",
            entity_type="entity",
            uid="XIPHOS-FB-18068"
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.98,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.95,
                "distinctive_tokens": ["ROSOBORONEXPORT"],
                "idf_token_score": 0.9,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="RU")
        
        self.assertEqual(disposition.category, "DEFINITE")
        self.assertEqual(disposition.confidence_band, "HIGH")
        self.assertEqual(disposition.recommended_action, "BLOCK")
        self.assertEqual(disposition.override_risk_weight, 1.0)
        self.assertIn("0.98", disposition.explanation)
    
    def test_definite_fallback_watchlist_match(self):
        """DEFINITE: Exact match on fallback watchlist (XIPHOS-FB-* UID)."""
        entry = SanctionEntry(
            name="DJI",
            aliases=["SZ DJI TECHNOLOGY"],
            program="CHINA-MILITARY-ENTITIES",
            list_type="ENTITY",
            country="CN",
            entity_type="entity",
            uid="XIPHOS-FB-1260H-DJI"
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.88,  # Below normal DEFINITE threshold
            matched_entry=entry,
            match_details={
                "sig_containment": 1.0,
                "distinctive_tokens": ["DJI"],
                "idf_token_score": 0.75,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="CN")
        
        self.assertEqual(disposition.category, "DEFINITE")
        self.assertEqual(disposition.recommended_action, "BLOCK")
        self.assertEqual(disposition.override_risk_weight, 1.0)
        self.assertIn("fallback watchlist", disposition.explanation)
    
    def test_definite_complete_token_containment_high_idf(self):
        """DEFINITE: Token containment=1.0 AND IDF score>=0.8."""
        entry = SanctionEntry(
            name="NORINCO",
            aliases=["CHINA NORTH INDUSTRIES"],
            program="CHINA-EO13959",
            list_type="ENTITY",
            country="CN",
            entity_type="entity",
            uid="XIPHOS-FB-33102"
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.82,  # Below normal DEFINITE threshold
            matched_entry=entry,
            match_details={
                "sig_containment": 1.0,
                "distinctive_tokens": ["NORINCO", "CHINA"],
                "idf_token_score": 0.85,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="CN")
        
        self.assertEqual(disposition.category, "DEFINITE")
        self.assertEqual(disposition.recommended_action, "BLOCK")
        self.assertEqual(disposition.override_risk_weight, 1.0)
        self.assertIn("complete token containment", disposition.explanation.lower())
    
    # =========================================================================
    # PROBABLE Classification Tests
    # =========================================================================
    
    def test_probable_mid_range_score_with_distinctive_tokens(self):
        """PROBABLE: 0.85-0.94 score with 2+ distinctive tokens, no country mismatch."""
        entry = SanctionEntry(
            name="HUAWEI TECHNOLOGIES CO LTD",
            aliases=["HUAWEI", "HUAWEI TECHNOLOGIES"],
            program="CHINA-EO13959",
            list_type="ENTITY",
            country="CN",
            entity_type="entity",
            uid="SDN-35012-HUAWEI"  # Use non-fallback UID to test PROBABLE logic
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.89,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.8,
                "distinctive_tokens": ["HUAWEI", "TECHNOLOGIES"],
                "idf_token_score": 0.75,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="CN")
        
        self.assertEqual(disposition.category, "PROBABLE")
        self.assertEqual(disposition.confidence_band, "MEDIUM")
        self.assertEqual(disposition.recommended_action, "ESCALATE")
        self.assertEqual(disposition.override_risk_weight, 0.85)
        self.assertIn("ESCALATE", disposition.explanation)
    
    def test_probable_adversary_nation_overrides_mismatch(self):
        """PROBABLE: 0.85-0.94 with country mismatch OK if entry is adversary nation."""
        entry = SanctionEntry(
            name="ROSTEC",
            aliases=["ROSTEC CORPORATION"],
            program="UKRAINE-EO13661",
            list_type="SDN",
            country="RU",  # Adversary nation
            entity_type="entity",
            uid="SDN-20939-ROSTEC"  # Use non-fallback UID
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.87,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.7,
                "distinctive_tokens": ["ROSTEC", "CORPORATION"],
                "idf_token_score": 0.72,
            }
        )
        
        # Vendor is from different country, but RU is adversary
        disposition = classify_alert(screening, vendor_country="SG")
        
        self.assertEqual(disposition.category, "PROBABLE")
        self.assertEqual(disposition.override_risk_weight, 0.85)
        self.assertIn("adversary nation", disposition.explanation.lower())
    
    # =========================================================================
    # POSSIBLE Classification Tests
    # =========================================================================
    
    def test_possible_mid_low_score_range(self):
        """POSSIBLE: 0.75-0.84 score classification."""
        entry = SanctionEntry(
            name="IRAN ELECTRONICS INDUSTRIES",
            aliases=["IEI", "SAIRAN"],
            program="IRAN",
            list_type="SDN",
            country="IR",
            entity_type="entity",
            uid="SDN-9649-IRAN-ELEC"  # Use non-fallback UID
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.79,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.6,
                "distinctive_tokens": ["ELECTRONICS"],
                "idf_token_score": 0.65,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="IR")
        
        self.assertEqual(disposition.category, "POSSIBLE")
        self.assertEqual(disposition.confidence_band, "LOW")
        self.assertEqual(disposition.recommended_action, "REVIEW")
        self.assertEqual(disposition.override_risk_weight, 0.60)
        self.assertIn("0.75-0.84", disposition.explanation)
    
    def test_possible_high_score_with_country_mismatch(self):
        """POSSIBLE: 0.85+ score downgraded by country mismatch (non-adversary entry)."""
        entry = SanctionEntry(
            name="EXAMPLE CORP DUBAI",
            aliases=["EXAMPLE CORP"],
            program="IRAN-SANCTIONS",
            list_type="SDN",
            country="AE",  # Non-adversary country (not in ADVERSARY_NATIONS)
            entity_type="entity",
            uid="SDN-99999-EXAMPLE"  # Use non-fallback UID
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.88,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.75,
                "distinctive_tokens": ["EXAMPLE", "CORP"],  # 2 distinctive tokens
                "idf_token_score": 0.70,
            }
        )
        
        # Vendor is from US (different country than entry's AE)
        disposition = classify_alert(screening, vendor_country="US")
        
        self.assertEqual(disposition.category, "POSSIBLE")
        self.assertEqual(disposition.override_risk_weight, 0.60)
        self.assertIn("Country mismatch", disposition.explanation)
    
    def test_possible_low_distinctive_tokens(self):
        """POSSIBLE: 0.85+ score downgraded by low distinctive token count."""
        entry = SanctionEntry(
            name="KOREA MINING DEVELOPMENT TRADING CORPORATION",
            aliases=["KOMID"],
            program="NORTH-KOREA",
            list_type="SDN",
            country="KP",
            entity_type="entity",
            uid="SDN-8985-KOMID"  # Use non-fallback UID
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.86,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.8,
                "distinctive_tokens": ["MINING"],  # Only 1 distinctive token
                "idf_token_score": 0.77,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="KP")
        
        self.assertEqual(disposition.category, "POSSIBLE")
        self.assertEqual(disposition.override_risk_weight, 0.60)
        self.assertIn("Low distinctive tokens", disposition.explanation)
    
    # =========================================================================
    # UNLIKELY Classification Tests
    # =========================================================================
    
    def test_unlikely_below_threshold(self):
        """UNLIKELY: Score < 0.75 returns AUTO_CLEAR action."""
        entry = SanctionEntry(
            name="SHANGHAI MICRO ELECTRONICS EQUIPMENT",
            aliases=["SMEE"],
            program="CHINA-EO13959",
            list_type="ENTITY",
            country="CN",
            entity_type="entity",
            uid="SDN-38901-SMEE"  # Use non-fallback UID
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.72,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.5,
                "distinctive_tokens": ["MICRO"],
                "idf_token_score": 0.60,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="CN")
        
        self.assertEqual(disposition.category, "UNLIKELY")
        self.assertEqual(disposition.confidence_band, "LOW")
        self.assertEqual(disposition.recommended_action, "AUTO_CLEAR")
        self.assertEqual(disposition.override_risk_weight, 0.0)
        self.assertIn("< 0.75", disposition.explanation)
    
    def test_unlikely_no_match(self):
        """UNLIKELY: Not matched at all returns AUTO_CLEAR immediately."""
        screening = self.create_mock_screening_result(
            matched=False,
            best_score=0.0,
            matched_entry=None,
            match_details={}
        )
        
        disposition = classify_alert(screening, vendor_country="US")
        
        self.assertEqual(disposition.category, "UNLIKELY")
        self.assertEqual(disposition.recommended_action, "AUTO_CLEAR")
        self.assertEqual(disposition.override_risk_weight, 0.0)
        # Check for "did not match" phrase in explanation
        self.assertIn("did not match", disposition.explanation.lower())
    
    # =========================================================================
    # Edge Cases and Override Logic Tests
    # =========================================================================
    
    def test_boundary_exact_0_95(self):
        """Edge case: score exactly 0.95 triggers DEFINITE."""
        entry = SanctionEntry(
            name="OBRONPROM",
            aliases=["OPK OBORONPROM"],
            program="UKRAINE-EO13661",
            list_type="SSI",
            country="RU",
            entity_type="entity",
            uid="SSI-18070-OBRONPROM"  # Use non-fallback UID to test 0.95 logic
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.95,  # Exactly at boundary
            matched_entry=entry,
            match_details={
                "sig_containment": 0.9,
                "distinctive_tokens": ["OBRONPROM"],
                "idf_token_score": 0.85,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="RU")
        self.assertEqual(disposition.category, "DEFINITE")
        self.assertEqual(disposition.override_risk_weight, 1.0)
    
    def test_boundary_0_85_probable(self):
        """Edge case: score exactly 0.85 with tokens triggers PROBABLE."""
        entry = SanctionEntry(
            name="WAGNER GROUP",
            aliases=["PMC WAGNER"],
            program="RUSSIA-EO14024",
            list_type="SDN",
            country="RU",
            entity_type="entity",
            uid="SDN-42215-WAGNER"  # Use non-fallback UID
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.85,  # Exactly at lower boundary
            matched_entry=entry,
            match_details={
                "sig_containment": 0.8,
                "distinctive_tokens": ["WAGNER", "GROUP"],
                "idf_token_score": 0.75,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="RU")
        self.assertEqual(disposition.category, "PROBABLE")
        self.assertEqual(disposition.override_risk_weight, 0.85)
    
    def test_boundary_0_75_possible(self):
        """Edge case: score exactly 0.75 triggers POSSIBLE."""
        entry = SanctionEntry(
            name="ZTE CORPORATION",
            aliases=["ZTE"],
            program="CHINA-NDAA-889",
            list_type="ENTITY",
            country="CN",
            entity_type="entity",
            uid="NDAA-889-ZTE"  # Use non-fallback UID
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.75,  # Exactly at threshold
            matched_entry=entry,
            match_details={
                "sig_containment": 0.7,
                "distinctive_tokens": ["ZTE"],
                "idf_token_score": 0.60,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="CN")
        self.assertEqual(disposition.category, "POSSIBLE")
        self.assertEqual(disposition.override_risk_weight, 0.60)
    
    def test_classification_factors_captured(self):
        """Verify classification_factors dict captures decision drivers."""
        entry = SanctionEntry(
            name="HIKVISION",
            aliases=["HIKVISION DIGITAL TECHNOLOGY"],
            program="CHINA-NDAA-889",
            list_type="ENTITY",
            country="CN",
            entity_type="entity",
            uid="XIPHOS-FB-889-HIKVISION"
        )
        
        screening = self.create_mock_screening_result(
            matched=True,
            best_score=0.91,
            matched_entry=entry,
            match_details={
                "sig_containment": 0.85,
                "distinctive_tokens": ["HIKVISION", "DIGITAL"],
                "idf_token_score": 0.82,
            }
        )
        
        disposition = classify_alert(screening, vendor_country="US")
        
        # Verify all key factors are in classification_factors
        self.assertIn("composite_score", disposition.classification_factors)
        self.assertIn("matched_entry_uid", disposition.classification_factors)
        self.assertIn("distinctive_tokens_count", disposition.classification_factors)
        self.assertIn("country_mismatch", disposition.classification_factors)
        self.assertEqual(disposition.classification_factors["composite_score"], 0.91)
        self.assertEqual(disposition.classification_factors["matched_entry_country"], "CN")
        self.assertEqual(disposition.classification_factors["distinctive_tokens_count"], 2)
    
    def test_adversary_nations_set(self):
        """Verify ADVERSARY_NATIONS contains expected countries."""
        expected = {"RU", "CN", "IR", "KP", "SY", "CU", "BY", "VE", "MM"}
        self.assertEqual(ADVERSARY_NATIONS, expected)
    
    # =========================================================================
    # Risk Weight Override Verification
    # =========================================================================
    
    def test_risk_weights_by_category(self):
        """Verify override_risk_weight values match spec per category."""
        test_cases = [
            (0.98, None, "DEFINITE", 1.0),      # High score
            (0.89, ["CORP", "TECH"], "PROBABLE", 0.85),  # 0.85-0.94 with tokens
            (0.79, ["CORP"], "POSSIBLE", 0.60),  # 0.75-0.84
            (0.70, [], "UNLIKELY", 0.0),         # < 0.75
        ]
        
        for score, tokens, expected_cat, expected_weight in test_cases:
            tokens = tokens or []
            entry = SanctionEntry(
                name="TEST CORP",
                aliases=["TEST"],
                program="TEST",
                list_type="TEST",
                country="CN",
                entity_type="entity",
                uid="TEST-UID"
            )
            
            screening = self.create_mock_screening_result(
                matched=True,
                best_score=score,
                matched_entry=entry if score > 0 else None,
                match_details={
                    "sig_containment": score,
                    "distinctive_tokens": tokens,
                    "idf_token_score": score * 0.8,
                }
            )
            
            disposition = classify_alert(screening, vendor_country="CN")
            self.assertEqual(disposition.category, expected_cat,
                           f"Score {score} should be {expected_cat}")
            self.assertEqual(disposition.override_risk_weight, expected_weight,
                           f"Weight for {expected_cat} should be {expected_weight}")


if __name__ == "__main__":
    unittest.main()
