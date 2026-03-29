from __future__ import annotations

import os
import sys


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_render_ownership_control_summary_surfaces_gap_descriptor_and_evidence():
    import dossier

    html = dossier._render_ownership_control_summary(
        {
            "oci": {
                "named_beneficial_owner_known": False,
                "owner_class_known": True,
                "owner_class": "Service-Disabled Veteran",
                "controlling_parent_known": False,
                "ownership_resolution_pct": 0.55,
                "control_resolution_pct": 0.35,
                "ownership_gap": "descriptor_only_owner_class",
                "descriptor_only": True,
                "owner_class_evidence": [
                    {
                        "descriptor": "Service-Disabled Veteran",
                        "title": "YSG article",
                        "source": "public_html_ownership",
                        "artifact": "https://www.ysginc.com/the-u-s-army-awards-offset-systems-group-829m-idiq-contract",
                        "confidence": 0.91,
                    }
                ],
            }
        }
    )

    assert "Ownership / control intelligence" in html
    assert "Descriptor-only" in html
    assert "Ownership gap" in html
    assert "Owner-class evidence" in html
    assert "Service-Disabled Veteran" in html
    assert "descriptor_only_owner_class".replace("_", " ").title() in html
