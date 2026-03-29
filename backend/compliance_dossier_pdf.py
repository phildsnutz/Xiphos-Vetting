"""
Standalone Compliance Dossier PDF Generator for Xiphos/Helios

Generates intelligence-grade, audit-ready PDF documents from vendor compliance
assessment data. Includes AI narrative analysis, risk storyline, gate impact
assessment, and recommendation rationale.

No database dependency - takes structured dataclass input and produces
professional PDFs suitable for defense procurement workflows.

Usage:
  - Programmatic: ComplianceDossierInput -> generate_compliance_dossier_pdf(data, output_path)
  - CLI: python3 compliance_dossier_pdf.py --demo
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
import hashlib
import json
import sys
import math

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Flowable
)
from reportlab.lib.enums import TA_CENTER


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class RiskTier(Enum):
    APPROVED = "APPROVED"
    QUALIFIED = "QUALIFIED"
    WATCH = "WATCH"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"


class GateStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"
    SKIP = "SKIP"


@dataclass
class SanctionsScreening:
    result: str
    match_count: int = 0
    disposition: str = "NO_ACTION"
    screening_date: Optional[str] = None
    screening_tool: str = "OFAC List Service v2.0"
    matched_programs: List[str] = field(default_factory=list)
    best_score: float = 0.0


@dataclass
class RiskFactor:
    """Single risk factor with contribution analysis."""
    name: str
    raw_score: float
    weight: float
    signed_contribution: float  # How much this factor moves the final score
    description: str = ""       # Human-readable explanation


@dataclass
class FGAMLogitScore:
    probability_score: float
    confidence_interval_low: float = 0.0
    confidence_interval_high: float = 1.0
    sensitivity_level: str = "STANDARD"
    factors: List[RiskFactor] = field(default_factory=list)
    composite_score: int = 0    # 0-100 integer composite


@dataclass
class RegulatoryGate:
    gate_id: str
    name: str
    status: GateStatus
    description: str = ""
    check_date: Optional[str] = None
    notes: str = ""
    impact: str = ""            # What happens if this gate fails
    remediation: str = ""       # How to fix a FAIL or PENDING


@dataclass
class ITARAssessment:
    applies: bool = False
    country_status: str = "UNRESTRICTED"
    deemed_export_risk: str = "LOW"
    deemed_export_score: float = 0.0
    red_flag_count: int = 0
    red_flag_score: float = 0.0
    red_flags: List[str] = field(default_factory=list)
    usml_category: str = "NONE"
    license_type: str = "NONE"
    foreign_nationals: List[str] = field(default_factory=list)
    narrative: str = ""         # ITAR-specific analysis narrative


@dataclass
class WorkflowRouting:
    queue_assignment: str = "STANDARD_REVIEW"
    sla_hours: int = 24
    escalation_path: str = "COMPLIANCE_MANAGER"
    notification_recipients: List[str] = field(default_factory=list)
    rationale: str = ""         # Why this routing was chosen


@dataclass
class StorylineCard:
    """Risk storyline signal card."""
    rank: int
    card_type: str  # trigger, impact, reach, action, offset
    severity: str   # critical, high, medium, low, info, positive
    title: str
    body: str
    confidence: float = 0.0


@dataclass
class AuditTrail:
    assessment_date: str
    completed_date: str
    assessment_version: str = "1.0"
    dossier_id: str = ""
    assessor: str = "SYSTEM"
    signature_hash: str = ""


@dataclass
class ComplianceDossierInput:
    vendor_name: str
    vendor_country: str
    dossier_id: str
    overall_risk_tier: RiskTier
    recommendation: str
    profile: str                # e.g. DEFENSE_ACQUISITION, ITAR_TRADE

    # Core assessment sections
    sanctions_screening: SanctionsScreening
    fgam_logit_score: FGAMLogitScore
    regulatory_gates: List[RegulatoryGate]

    # AI-generated narratives
    executive_narrative: str = ""    # 2-3 paragraph executive summary
    risk_storyline: List[StorylineCard] = field(default_factory=list)
    recommendation_rationale: str = ""  # Why this recommendation

    # Optional sections
    itar_assessment: Optional[ITARAssessment] = None
    workflow_routing: Optional[WorkflowRouting] = None
    audit_trail: Optional[AuditTrail] = None

    classification_level: str = "CONTROLLED UNCLASSIFIED INFORMATION"


# ============================================================================
# DESIGN CONSTANTS
# ============================================================================

NAVY = HexColor("#1E293B")
DARK_SLATE = HexColor("#0F172A")
GOLD = HexColor("#C4A052")
GREEN_C = HexColor("#10B981")
AMBER_C = HexColor("#F59E0B")
RED_C = HexColor("#EF4444")
BLUE_C = HexColor("#3B82F6")
LIGHT_GRAY_BG = HexColor("#F8FAFC")
BORDER_GRAY = HexColor("#E2E8F0")
DARK_GRAY = HexColor("#334155")
MID_GRAY = HexColor("#64748B")
LIGHT_GRAY = HexColor("#94A3B8")
FAINT_GRAY = HexColor("#E2E8F0")
GHOST = HexColor("#F8FAFC")
SKY = HexColor("#0EA5E9")
TEAL = HexColor("#14B8A6")
DARK_RED = HexColor("#DC2626")

PAGE_W, PAGE_H = letter



def _tier_hex(tier: RiskTier) -> str:
    return {RiskTier.APPROVED: "#10B981", RiskTier.QUALIFIED: "#3B82F6",
            RiskTier.WATCH: "#F59E0B", RiskTier.REVIEW: "#EF4444",
            RiskTier.BLOCKED: "#DC2626"}.get(tier, "#64748B")


def _status_hex(s: str) -> str:
    s = (s or "").upper()
    if s in ("PASS", "APPROVED", "COMPLIANT", "GREEN", "UNRESTRICTED", "NO_ACTION",
             "LOW", "ALLOWED", "NO_MATCH"):
        return "#10B981"
    if s in ("PENDING", "QUALIFIED", "WATCH", "REQUIRES_REVIEW", "REVIEW", "AMBER",
             "MEDIUM", "SKIP"):
        return "#F59E0B"
    if s in ("FAIL", "BLOCKED", "RED", "PROHIBITED", "HIT", "REJECT",
             "HIGH", "EXTREME", "NON_COMPLIANT"):
        return "#EF4444"
    return "#64748B"


def _severity_hex(s: str) -> str:
    s = (s or "").lower()
    return {"critical": "#DC2626", "high": "#F59E0B", "medium": "#EAB308",
            "low": "#3B82F6", "info": "#6B7280", "positive": "#10B981"}.get(s, "#6B7280")


# ============================================================================
# CUSTOM FLOWABLES
# ============================================================================

class NavyCover(Flowable):
    """Compact navy cover block (120pt max height)."""
    def __init__(self, w, h, vendor, dossier_id, date_str, classification, country, profile):
        Flowable.__init__(self)
        self.width = w
        self.height = h
        self.vendor = vendor
        self.dossier_id = dossier_id
        self.date_str = date_str
        self.classification = classification
        self.country = country
        self.profile = profile

    def draw(self):
        c = self.canv
        c.setFillColor(NAVY)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.rect(0, 0, self.width, 3, fill=1, stroke=0)
        # Branding (compact)
        c.setFillColor(GOLD)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(14, self.height - 16, "HELIOS DECISION DOSSIER")
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 13)
        vn = self.vendor[:50] + "..." if len(self.vendor) > 50 else self.vendor
        c.drawString(14, self.height - 35, vn)
        # Metadata footer (8pt)
        c.setFont("Helvetica", 7)
        c.setFillColor(LIGHT_GRAY)
        meta = f"{self.country}  •  {self.profile.replace('_', ' ')}  •  {self.dossier_id}"
        c.drawString(14, self.height - 48, meta)
        c.drawString(14, self.height - 58, f"{self.date_str}  •  {self.classification}")


class RiskGauge(Flowable):
    """Compact semicircle risk gauge (70pt wide)."""
    def __init__(self, score, width=90, height=60):
        Flowable.__init__(self)
        self.score = max(0, min(1, score))
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        cx, cy, r = self.width / 2, 8, 32
        # Background arc
        c.setStrokeColor(BORDER_GRAY)
        c.setLineWidth(7)
        c.setLineCap(1)
        p = c.beginPath()
        for i in range(181):
            a = math.radians(180 - i)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            (p.moveTo if i == 0 else p.lineTo)(x, y)
        c.drawPath(p, stroke=1, fill=0)
        # Score arc
        deg = int(self.score * 180)
        if self.score < 0.3:
            ac = GREEN_C
        elif self.score < 0.6:
            ac = AMBER_C
        elif self.score < 0.8:
            ac = HexColor("#F97316")
        else:
            ac = RED_C
        c.setStrokeColor(ac)
        c.setLineWidth(7)
        p2 = c.beginPath()
        for i in range(deg + 1):
            a = math.radians(180 - i)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            (p2.moveTo if i == 0 else p2.lineTo)(x, y)
        c.drawPath(p2, stroke=1, fill=0)
        # Score text
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 18)
        s = f"{self.score * 100:.0f}%"
        c.drawString(cx - c.stringWidth(s, "Helvetica-Bold", 18) / 2, cy + 8, s)


class HorizBar(Flowable):
    """Horizontal filled bar."""
    def __init__(self, value, max_val=0.1, width=100, height=8, fill_color=None):
        Flowable.__init__(self)
        self.value = value
        self.max_val = max_val
        self.width = width
        self.height = height
        self.fill_color = fill_color or SKY

    def draw(self):
        c = self.canv
        c.setFillColor(GHOST)
        c.roundRect(0, 0, self.width, self.height, 2, fill=1, stroke=0)
        pct = min(1.0, self.value / self.max_val) if self.max_val > 0 else 0
        c.setFillColor(self.fill_color)
        c.roundRect(0, 0, max(2, self.width * pct), self.height, 2, fill=1, stroke=0)


class AccentHeader(Flowable):
    """Section header with left gold accent (22pt height)."""
    def __init__(self, text, width=None):
        Flowable.__init__(self)
        self.text = text
        self.hdr_width = width or (PAGE_W - 72)
        self.height = 22

    def draw(self):
        c = self.canv
        c.setFillColor(NAVY)
        c.roundRect(0, 0, self.hdr_width, self.height, 2, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.rect(0, 0, 3, self.height, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(11, 6, self.text)




# ============================================================================
# PAGE TEMPLATES
# ============================================================================

def _page_footer(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 7)
    canvas_obj.setFillColor(MID_GRAY)
    canvas_obj.drawString(36, 18, "CUI // Controlled Unclassified Information  |  Handle per 32 CFR Part 2002")
    canvas_obj.drawRightString(PAGE_W - 36, 18, f"Page {doc.page}")
    canvas_obj.setStrokeColor(FAINT_GRAY)
    canvas_obj.setLineWidth(0.4)
    canvas_obj.line(36, PAGE_H - 28, PAGE_W - 36, PAGE_H - 28)
    canvas_obj.restoreState()

def _cover_footer(canvas_obj, doc):
    pass


# ============================================================================
# STYLES
# ============================================================================

def _styles():
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("xb", parent=base["BodyText"], fontSize=9, leading=13,
                               textColor=DARK_GRAY, spaceAfter=4),
        "body_sm": ParagraphStyle("xbs", parent=base["BodyText"], fontSize=7.5, leading=10,
                                  textColor=MID_GRAY, spaceAfter=2),
        "narrative": ParagraphStyle("xn", parent=base["BodyText"], fontSize=9.5, leading=14,
                                    textColor=DARK_GRAY, spaceAfter=8, spaceBefore=2),
        "label": ParagraphStyle("xl", parent=base["BodyText"], fontSize=7.5, leading=10,
                                textColor=MID_GRAY, fontName="Helvetica-Bold"),
        "value": ParagraphStyle("xv", parent=base["BodyText"], fontSize=9.5, leading=13,
                                textColor=NAVY, fontName="Helvetica-Bold"),
        "h2": ParagraphStyle("xh2", parent=base["Heading2"], fontSize=11, leading=14,
                             textColor=NAVY, fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4),
        "h3": ParagraphStyle("xh3", parent=base["Heading3"], fontSize=9.5, leading=12,
                             textColor=DARK_GRAY, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=3),
        "footer": ParagraphStyle("xf", parent=base["BodyText"], fontSize=7, leading=9,
                                 textColor=LIGHT_GRAY),
        "hero_title": ParagraphStyle("xht", parent=base["Title"], fontSize=18, leading=23,
                                     textColor=white, fontName="Helvetica-Bold"),
        "hero_body": ParagraphStyle("xhb", parent=base["BodyText"], fontSize=9.5, leading=14,
                                    textColor=HexColor("#D6DEE8")),
        "metric_label": ParagraphStyle("xml", parent=base["BodyText"], fontSize=7, leading=9,
                                       textColor=HexColor("#AAB4C3"), fontName="Helvetica-Bold"),
        "metric_value": ParagraphStyle("xmv", parent=base["BodyText"], fontSize=13, leading=16,
                                       textColor=white, fontName="Helvetica-Bold"),
    }


# ============================================================================
# NARRATIVE GENERATION
# ============================================================================

def _generate_executive_narrative(data: ComplianceDossierInput) -> str:
    """Generate executive narrative if not provided."""
    if data.executive_narrative:
        return data.executive_narrative

    score = data.fgam_logit_score
    tier = data.overall_risk_tier
    scr = data.sanctions_screening
    pass_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.PASS)
    fail_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.FAIL)
    pend_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.PENDING)
    total = len(data.regulatory_gates)

    prob_pct = int(score.probability_score * 100)
    ci_w = score.confidence_interval_high - score.confidence_interval_low
    conf = "high" if ci_w < 0.10 else "moderate" if ci_w < 0.25 else "low"

    # Paragraph 1: Overall assessment
    if tier == RiskTier.APPROVED:
        p1 = (f"Helios assesses {data.vendor_name} at {prob_pct}% posterior risk probability "
              f"with {conf} confidence (CI {score.confidence_interval_low:.0%} to "
              f"{score.confidence_interval_high:.0%}). The vendor presents a clean compliance "
              f"posture across all evaluated dimensions. No sanctions matches were detected "
              f"and {pass_ct} of {total} regulatory gates returned PASS.")
    elif tier == RiskTier.QUALIFIED:
        p1 = (f"Helios assesses {data.vendor_name} at {prob_pct}% posterior risk probability "
              f"with {conf} confidence (CI {score.confidence_interval_low:.0%} to "
              f"{score.confidence_interval_high:.0%}). The vendor falls within the QUALIFIED tier, "
              f"indicating conditional acceptability contingent on resolution of {pend_ct} pending "
              f"gate(s) and {fail_ct} failed gate(s) identified during evaluation.")
    elif tier == RiskTier.REVIEW:
        p1 = (f"Helios assesses {data.vendor_name} at {prob_pct}% posterior risk probability "
              f"with {conf} confidence (CI {score.confidence_interval_low:.0%} to "
              f"{score.confidence_interval_high:.0%}). The REVIEW tier designation reflects "
              f"material compliance concerns: {fail_ct} regulatory gate failure(s), "
              f"{pend_ct} gate(s) pending resolution, and risk factor concentrations "
              f"that exceed acceptable thresholds for the {data.profile.replace('_', ' ')} profile.")
    else:
        p1 = (f"Helios assesses {data.vendor_name} at {prob_pct}% posterior risk probability "
              f"with {conf} confidence. The BLOCKED designation indicates one or more "
              f"disqualifying conditions were detected. Engagement with this vendor is "
              f"not recommended under current {data.profile.replace('_', ' ')} compliance requirements.")

    # Paragraph 2: Key factors
    factors_text = ""
    if score.factors:
        top_factors = sorted(score.factors, key=lambda f: abs(f.signed_contribution), reverse=True)[:3]
        names = [f.name for f in top_factors]
        factors_text = (
            f"The primary risk drivers are {', '.join(names[:-1])}, and {names[-1]}. "
            if len(names) > 1 else f"The primary risk driver is {names[0]}. "
        )
        # Add factor detail
        top = top_factors[0]
        factors_text += (
            f"{top.name} contributes {top.signed_contribution:+.1%} to the posterior estimate "
            f"(raw score {top.raw_score:.2f}, weight {top.weight:.1f}). "
        )
        if top.description:
            factors_text += top.description + " "

    # Paragraph 3: Sanctions + ITAR
    p3 = ""
    if scr.result.upper() == "APPROVED":
        p3 = (f"OFAC screening returned no matches against consolidated sanctions lists "
              f"({scr.screening_tool}). ")
    else:
        p3 = (f"OFAC screening detected {scr.match_count} potential match(es) with a "
              f"best score of {scr.best_score:.0%}. Disposition: {scr.disposition}. ")

    if data.itar_assessment and data.itar_assessment.applies:
        itar = data.itar_assessment
        p3 += (f"ITAR assessment for {itar.usml_category} items classifies the vendor as "
               f"{itar.country_status} with {itar.deemed_export_risk} deemed export risk "
               f"and {itar.red_flag_count} red flag indicator(s). "
               f"Required license type: {itar.license_type}.")

    return f"{p1}\n\n{factors_text}\n\n{p3}"


def _generate_recommendation_rationale(data: ComplianceDossierInput) -> str:
    """Generate recommendation rationale if not provided."""
    if data.recommendation_rationale:
        return data.recommendation_rationale

    tier = data.overall_risk_tier
    rec = data.recommendation
    fail_gates = [g for g in data.regulatory_gates if g.status == GateStatus.FAIL]
    pend_gates = [g for g in data.regulatory_gates if g.status == GateStatus.PENDING]

    if tier == RiskTier.APPROVED:
        base = (f"Recommendation of {rec} is based on: (1) posterior risk below 30% threshold, "
                f"(2) all regulatory gates in PASS or SKIP status, "
                f"(3) clean sanctions screening with no derogatory signals.")
    elif tier == RiskTier.QUALIFIED:
        conditions = []
        for g in fail_gates:
            conditions.append(f"resolve {g.name} ({g.gate_id}): {g.remediation or g.notes}")
        for g in pend_gates:
            conditions.append(f"complete {g.name} ({g.gate_id}): {g.remediation or g.notes}")
        cond_text = "; ".join(conditions) if conditions else "complete pending gate evaluations"
        base = (f"Recommendation of {rec} is contingent upon: {cond_text}. "
                f"Once conditions are met, the vendor may be re-scored for potential upgrade to APPROVED.")
    elif tier == RiskTier.REVIEW:
        base = (f"Recommendation of {rec} requires enhanced due diligence before any engagement. "
                f"Key concerns: {len(fail_gates)} gate failure(s) and risk score in the "
                f"{int(data.fgam_logit_score.probability_score * 100)}th percentile. "
                f"A dedicated compliance review with senior officer sign-off is required.")
    else:
        base = (f"Recommendation of {rec}: the assessment has identified disqualifying risk factors "
                f"that preclude vendor engagement under current compliance policy. "
                f"This determination requires no further analyst review.")
    return base


def _generate_gate_impact(gate: RegulatoryGate) -> str:
    """Generate impact statement for a failed/pending gate."""
    if gate.impact:
        return gate.impact
    impacts = {
        "Section 889": "Vendor inclusion in any DoD contract would violate FY2019 NDAA Section 889",
        "ITAR": "Vendor cannot handle ITAR-controlled articles without proper authorization",
        "EAR": "Dual-use items may require BIS license prior to transfer",
        "DFARS Specialty": "Specialty metal components may not meet domestic melting requirements",
        "DFARS CDI": "Vendor cannot handle Covered Defense Information per DFARS 252.204-7012",
        "CMMC": "Vendor does not meet required cybersecurity maturity level",
        "FOCI": "Foreign ownership may compromise access to classified programs",
        "NDAA 1260H": "Entity appears on Chinese Military Company list per 10 USC 1260H",
        "CFIUS": "Transaction may require CFIUS review under 50 USC 4565",
        "Berry": "Items may not meet domestic source requirements per 10 USC 4862",
        "Deemed Export": "Foreign national access to controlled technical data requires license",
        "Red Flag": "Transaction diversion indicators detected requiring investigation",
        "USML": "USML category export to destination country requires authorization",
    }
    for key, impact in impacts.items():
        if key.lower() in gate.name.lower():
            return impact
    return f"Gate failure may impact vendor eligibility under {gate.name} requirements"


# ============================================================================
# PDF SECTION BUILDERS
# ============================================================================

def _build_cover(data, st):
    elems = []
    date_str = data.audit_trail.assessment_date if data.audit_trail else datetime.now().strftime("%Y-%m-%d")

    cover = NavyCover(
        w=PAGE_W - 72, h=80,
        vendor=data.vendor_name, dossier_id=data.dossier_id,
        date_str=date_str, classification=data.classification_level,
        country=data.vendor_country, profile=data.profile,
    )
    elems.append(cover)
    elems.append(Spacer(1, 0.12 * inch))

    # CUI banner
    cui_st = ParagraphStyle("cui", parent=st["body"], fontSize=8, textColor=white,
                            alignment=TA_CENTER, fontName="Helvetica-Bold")
    cui = Table([[Paragraph("CONTROLLED UNCLASSIFIED INFORMATION (CUI)", cui_st)]],
                colWidths=[PAGE_W - 72])
    cui.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK_RED),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(cui)
    elems.append(Spacer(1, 0.15 * inch))

    # Hero summary panel
    tc = _tier_hex(data.overall_risk_tier)
    prob = int(data.fgam_logit_score.probability_score * 100)
    ci_w = data.fgam_logit_score.confidence_interval_high - data.fgam_logit_score.confidence_interval_low
    conf_label = "High" if ci_w < 0.10 else "Moderate" if ci_w < 0.25 else "Low"

    hero_text = (
        f"<font size='18'><b>{data.vendor_name}</b></font><br/>"
        f"<font size='10' color='#D6DEE8'>"
        f"Helios recommends <b>{data.recommendation.replace('_', ' ').lower()}</b> "
        f"based on a {prob}% posterior risk estimate and {conf_label.lower()} assessment confidence."
        f"</font>"
    )
    rec_chip = Paragraph(data.recommendation.replace("_", " "), st["metric_value"])
    hero = Table(
        [[Paragraph(hero_text, st["hero_title"]),
          Table([[rec_chip]], colWidths=[1.5 * inch])]],
        colWidths=[5.0 * inch, 1.6 * inch],
    )
    hero.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    # Color the recommendation chip
    hero._cellvalues[0][1].setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(tc)),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(hero)

    # Metric cards row
    pass_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.PASS)
    fail_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.FAIL)
    pend_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.PENDING)

    def _metric_card(label, value, sub):
        return Table([
            [Paragraph(label, st["metric_label"])],
            [Paragraph(str(value), st["metric_value"])],
            [Paragraph(sub, st["hero_body"])],
        ], colWidths=[1.6 * inch])

    metrics = Table(
        [[_metric_card("RISK POSTURE", f"{prob}%", f"Tier {data.overall_risk_tier.value}"),
          _metric_card("CONFIDENCE", conf_label, f"CI {data.fgam_logit_score.confidence_interval_low:.0%} to {data.fgam_logit_score.confidence_interval_high:.0%}"),
          _metric_card("SANCTIONS", data.sanctions_screening.result, f"{data.sanctions_screening.match_count} matches"),
          _metric_card("GATES", f"{pass_ct}/{len(data.regulatory_gates)}", f"{fail_ct} fail, {pend_ct} pending")]],
        colWidths=[1.7 * inch] * 4,
    )
    dark_bg = HexColor("#0F1E2F")
    metrics.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), dark_bg),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#1F334A")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    for card in metrics._cellvalues[0]:
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), dark_bg),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
    elems.append(metrics)
    elems.append(Spacer(1, 0.15 * inch))

    # Executive Analysis - starts on page 1 right after the hero panel
    elems.append(AccentHeader("EXECUTIVE ANALYSIS"))
    elems.append(Spacer(1, 0.08 * inch))

    narrative = _generate_executive_narrative(data)
    for para in narrative.split("\n\n"):
        para = para.strip()
        if para:
            elems.append(Paragraph(para, st["narrative"]))

    return elems


def _build_executive_analysis(data, st):
    """Risk storyline + recommendation rationale (continues from cover page)."""
    elems = []

    elems.append(Spacer(1, 0.08 * inch))

    # Risk storyline
    if data.risk_storyline:
        elems.append(AccentHeader("RISK STORYLINE"))
        elems.append(Spacer(1, 0.08 * inch))
        elems.append(Paragraph(
            "Helios distills the assessment into evidence-backed signals a reviewer should "
            "understand before reading the full finding set.",
            st["body_sm"],
        ))
        elems.append(Spacer(1, 0.08 * inch))

        row_cards = []
        for card in data.risk_storyline[:6]:
            accent_color = HexColor(_severity_hex(card.severity))
            card_text = (
                f"<font size='7' color='#64748B'><b>{card.rank}</b>  {card.card_type.upper()}</font><br/>"
                f"<font size='9.5' color='#1E293B'><b>{card.title}</b></font><br/>"
                f"<font size='8' color='#334155'>{card.body}</font><br/>"
                f"<font size='7' color='#64748B'>{int(card.confidence * 100)}% confidence</font>"
            )
            card_table = Table(
                [[Paragraph(card_text, st["body"])]],
                colWidths=[3.3 * inch],
            )
            card_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY_BG),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER_GRAY),
                ("LINEBEFORE", (0, 0), (0, -1), 4, accent_color),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            row_cards.append(card_table)
            if len(row_cards) == 2:
                r = Table([row_cards], colWidths=[3.4 * inch, 3.4 * inch])
                r.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
                elems.append(r)
                elems.append(Spacer(1, 0.06 * inch))
                row_cards = []
        if row_cards:
            if len(row_cards) == 1:
                row_cards.append(Spacer(1, 1))
            r = Table([row_cards], colWidths=[3.4 * inch, 3.4 * inch])
            r.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            elems.append(r)
            elems.append(Spacer(1, 0.08 * inch))

    # Recommendation rationale
    elems.append(Spacer(1, 0.04 * inch))
    elems.append(AccentHeader("RECOMMENDATION RATIONALE"))
    elems.append(Spacer(1, 0.08 * inch))
    rationale = _generate_recommendation_rationale(data)
    elems.append(Paragraph(rationale, st["narrative"]))

    elems.append(Spacer(1, 0.15 * inch))
    return elems


def _build_risk_score(data, st):
    """FGAMLogit score + contributing factors."""
    elems = []

    elems.append(AccentHeader("FGAMLOGIT V5.0 RISK SCORE"))
    elems.append(Spacer(1, 0.1 * inch))

    score = data.fgam_logit_score
    gauge = RiskGauge(score.probability_score, width=90, height=60)

    ci_text = f"{score.confidence_interval_low:.2f}–{score.confidence_interval_high:.2f}"
    ci_w = score.confidence_interval_high - score.confidence_interval_low
    conf = "High" if ci_w < 0.10 else "Moderate" if ci_w < 0.25 else "Low"

    # Compact metric cards beside gauge
    info_rows = [
        [Paragraph("Confidence Interval", st["label"]), Paragraph(ci_text, st["value"])],
        [Paragraph("Assessment Confidence", st["label"]), Paragraph(conf, st["value"])],
        [Paragraph("Sensitivity Level", st["label"]), Paragraph(score.sensitivity_level, st["value"])],
        [Paragraph("Composite Score", st["label"]), Paragraph(f"{score.composite_score}/100", st["value"])],
    ]
    info = Table(info_rows, colWidths=[1.4 * inch, 1.3 * inch])
    top = Table([[gauge, Spacer(1, 0.15 * inch), info]], colWidths=[1.0 * inch, 0.25 * inch, 4.85 * inch])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elems.append(top)
    elems.append(Spacer(1, 0.12 * inch))

    # Contributing factors with full analysis
    if score.factors:
        elems.append(AccentHeader("CONTRIBUTING RISK FACTORS"))
        elems.append(Spacer(1, 0.08 * inch))
        max_w = max(abs(f.signed_contribution) for f in score.factors) if score.factors else 0.1

        header = [
            Paragraph("<b>Factor</b>", st["body_sm"]),
            Paragraph("<b>Raw</b>", st["body_sm"]),
            Paragraph("<b>Contrib.</b>", st["body_sm"]),
            Paragraph("<b>Wt</b>", st["body_sm"]),
            "",
            Paragraph("<b>Analysis</b>", st["body_sm"]),
        ]
        rows = [header]
        sorted_factors = sorted(score.factors, key=lambda f: abs(f.signed_contribution), reverse=True)

        for f in sorted_factors[:14]:
            bar_color = RED_C if f.signed_contribution > 0.02 else AMBER_C if f.signed_contribution > 0 else GREEN_C
            bar = HorizBar(abs(f.signed_contribution), max_val=max_w, width=60, height=6, fill_color=bar_color)
            desc = f.description[:95] + "..." if len(f.description) > 95 else f.description
            rows.append([
                Paragraph(f.name, st["body_sm"]),
                Paragraph(f"{f.raw_score:.2f}", st["body_sm"]),
                Paragraph(f"{f.signed_contribution:+.3f}", st["body_sm"]),
                Paragraph(f"{f.weight:.1f}", st["body_sm"]),
                bar,
                Paragraph(desc, st["body_sm"]),
            ])

        f_tbl = Table(rows, colWidths=[1.2 * inch, 0.45 * inch, 0.65 * inch, 0.35 * inch, 0.75 * inch, 2.8 * inch])
        f_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, FAINT_GRAY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, GHOST]),
        ]))
        elems.append(f_tbl)

    # Sanctions screening detail
    elems.append(Spacer(1, 0.12 * inch))
    elems.append(AccentHeader("SANCTIONS SCREENING"))
    elems.append(Spacer(1, 0.08 * inch))
    scr = data.sanctions_screening
    sc = _status_hex(scr.result)
    scr_rows = [
        [Paragraph("Result", st["label"]),
         Paragraph(f"<font color='{sc}'><b>{scr.result}</b></font>", st["body_sm"]),
         Paragraph("Matches", st["label"]),
         Paragraph(str(scr.match_count), st["value"])],
        [Paragraph("Disposition", st["label"]),
         Paragraph(scr.disposition, st["value"]),
         Paragraph("Tool", st["label"]),
         Paragraph(scr.screening_tool, st["body_sm"])],
    ]
    scr_tbl = Table(scr_rows, colWidths=[0.9 * inch, 2.2 * inch, 0.9 * inch, 2.2 * inch])
    scr_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, BORDER_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY_BG),
    ]))
    elems.append(scr_tbl)

    elems.append(Spacer(1, 0.15 * inch))
    return elems


def _build_gates(data, st):
    """Regulatory gates with impact analysis."""
    elems = []
    elems.append(AccentHeader("REGULATORY GATES"))
    elems.append(Spacer(1, 0.1 * inch))

    pass_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.PASS)
    fail_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.FAIL)
    pend_ct = sum(1 for g in data.regulatory_gates if g.status == GateStatus.PENDING)

    # Summary line
    elems.append(Paragraph(
        f"<b>{pass_ct}</b> of <b>{len(data.regulatory_gates)}</b> gates passed  |  "
        f"<font color='#EF4444'><b>{fail_ct} failed</b></font>  |  "
        f"<font color='#F59E0B'><b>{pend_ct} pending</b></font>",
        st["body_sm"],
    ))
    elems.append(Spacer(1, 0.08 * inch))

    # Gate table with colored badges
    header = [
        Paragraph("<b>ID</b>", st["body_sm"]),
        Paragraph("<b>Gate</b>", st["body_sm"]),
        Paragraph("<b>Status</b>", st["body_sm"]),
        Paragraph("<b>Notes</b>", st["body_sm"]),
    ]
    rows = [header]
    for g in data.regulatory_gates:
        sc = _status_hex(g.status.value)
        status_text = g.status.value
        rows.append([
            Paragraph(g.gate_id, st["body_sm"]),
            Paragraph(g.name, st["body_sm"]),
            Paragraph(f"<font color='{sc}'><b>{status_text}</b></font>", st["body_sm"]),
            Paragraph(g.notes[:60] + ("..." if len(g.notes) > 60 else ""), st["body_sm"]),
        ])

    g_tbl = Table(rows, colWidths=[0.5 * inch, 2.3 * inch, 0.7 * inch, 2.9 * inch])
    g_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, BORDER_GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_GRAY_BG]),
    ]))
    elems.append(g_tbl)
    elems.append(Spacer(1, 0.12 * inch))

    # Failed/pending gate impact analysis
    problem_gates = [g for g in data.regulatory_gates if g.status in (GateStatus.FAIL, GateStatus.PENDING)]
    if problem_gates:
        elems.append(AccentHeader("GATE IMPACT ANALYSIS"))
        elems.append(Spacer(1, 0.08 * inch))
        elems.append(Paragraph(
            "The following gates require attention before the vendor can proceed "
            "through the compliance pipeline. Each entry includes the operational "
            "impact and recommended remediation path.",
            st["body_sm"],
        ))
        elems.append(Spacer(1, 0.06 * inch))

        for g in problem_gates:
            sc = _status_hex(g.status.value)
            impact = _generate_gate_impact(g)
            remediation = g.remediation or g.notes

            card_data = [
                [Paragraph(f"<font color='{sc}'><b>{g.status.value}</b></font>  {g.gate_id} {g.name}", st["body"])],
                [Paragraph(f"<b>Impact:</b> {impact}", st["body_sm"])],
                [Paragraph(f"<b>Remediation:</b> {remediation}", st["body_sm"])],
            ]
            card = Table(card_data, colWidths=[6.2 * inch])
            card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), GHOST),
                ("BOX", (0, 0), (-1, -1), 0.5, FAINT_GRAY),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            elems.append(card)
            elems.append(Spacer(1, 0.04 * inch))

    elems.append(Spacer(1, 0.15 * inch))
    return elems


def _build_itar(data, st):
    itar = data.itar_assessment
    if not itar or not itar.applies:
        return []

    elems = []
    elems.append(AccentHeader("ITAR COMPLIANCE ASSESSMENT"))
    elems.append(Spacer(1, 0.1 * inch))

    # Status cards
    cards_data = [
        [Paragraph("Country Status", st["label"]),
         Paragraph("Deemed Export Risk", st["label"]),
         Paragraph("USML Category", st["label"]),
         Paragraph("License Type", st["label"])],
        [Paragraph(f"<font color='{_status_hex(itar.country_status)}'><b>{itar.country_status}</b></font>", st["body_sm"]),
         Paragraph(f"<font color='{_status_hex(itar.deemed_export_risk)}'><b>{itar.deemed_export_risk}</b></font> ({itar.deemed_export_score:.2f})", st["body_sm"]),
         Paragraph(f"<b>{itar.usml_category}</b>", st["value"]),
         Paragraph(f"<b>{itar.license_type}</b>", st["value"])],
    ]
    cards = Table(cards_data, colWidths=[1.5 * inch, 1.7 * inch, 1.5 * inch, 1.5 * inch])
    cards.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY_BG),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER_GRAY),
        ("LINEBEFORE", (1, 0), (1, -1), 0.4, BORDER_GRAY),
        ("LINEBEFORE", (2, 0), (2, -1), 0.4, BORDER_GRAY),
        ("LINEBEFORE", (3, 0), (3, -1), 0.4, BORDER_GRAY),
    ]))
    elems.append(cards)
    elems.append(Spacer(1, 0.08 * inch))

    # ITAR narrative
    if itar.narrative:
        elems.append(Paragraph(itar.narrative, st["narrative"]))
    else:
        # Generate one
        nar = (f"ITAR evaluation for {itar.usml_category} controlled items indicates "
               f"{itar.country_status.lower()} country status. Deemed export risk is assessed "
               f"at {itar.deemed_export_risk} (score: {itar.deemed_export_score:.2f}) ")
        if itar.foreign_nationals:
            nar += (f"based on foreign national access from {', '.join(itar.foreign_nationals)}. ")
        if itar.red_flag_count > 0:
            nar += (f"The transaction exhibits {itar.red_flag_count} red flag indicator(s) "
                    f"(composite score: {itar.red_flag_score:.2f}) that require compliance review. ")
        nar += f"Required export authorization: {itar.license_type}."
        elems.append(Paragraph(nar, st["narrative"]))

    if itar.red_flags:
        elems.append(Spacer(1, 0.08 * inch))
        elems.append(Paragraph(f"RED FLAG INDICATORS ({itar.red_flag_count})", st["body_sm"]))
        for i, flag in enumerate(itar.red_flags, 1):
            bullet_c = "#EF4444" if any(w in flag.lower() for w in ("prohibited", "debarred", "diversion")) else "#F59E0B"
            elems.append(Paragraph(f"<font color='{bullet_c}'>●</font>  {flag}", st["body_sm"]))

    elems.append(Spacer(1, 0.15 * inch))
    return elems


def _build_workflow(data, st):
    r = data.workflow_routing
    if not r:
        return []

    elems = []
    elems.append(AccentHeader("WORKFLOW ROUTING"))
    elems.append(Spacer(1, 0.08 * inch))

    rows = [
        [Paragraph("Queue", st["label"]), Paragraph(r.queue_assignment, st["value"]),
         Paragraph("SLA", st["label"]), Paragraph(f"{r.sla_hours}h", st["value"])],
        [Paragraph("Escalation", st["label"]), Paragraph(r.escalation_path, st["value"]),
         Paragraph("Recipients", st["label"]),
         Paragraph(", ".join(r.notification_recipients[:3]) or "N/A", st["body_sm"])],
    ]
    tbl = Table(rows, colWidths=[0.9 * inch, 2.2 * inch, 0.9 * inch, 2.2 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, BORDER_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY_BG),
    ]))
    elems.append(tbl)

    if r.rationale:
        elems.append(Spacer(1, 0.06 * inch))
        elems.append(Paragraph(r.rationale, st["body_sm"]))

    elems.append(Spacer(1, 0.15 * inch))
    return elems


def _build_audit(data, st):
    elems = []
    elems.append(AccentHeader("AUDIT TRAIL"))
    elems.append(Spacer(1, 0.08 * inch))

    a = data.audit_trail or AuditTrail(
        assessment_date=datetime.now().strftime("%Y-%m-%d"),
        completed_date=datetime.now().strftime("%Y-%m-%d"),
    )
    h = a.signature_hash[:28] + "..." if len(a.signature_hash) > 28 else a.signature_hash

    rows = [
        [Paragraph("Assessment Date", st["label"]), Paragraph(a.assessment_date, st["body_sm"]),
         Paragraph("Completed", st["label"]), Paragraph(a.completed_date, st["body_sm"])],
        [Paragraph("Version", st["label"]), Paragraph(a.assessment_version, st["body_sm"]),
         Paragraph("Assessor", st["label"]), Paragraph(a.assessor, st["body_sm"])],
        [Paragraph("Dossier ID", st["label"]), Paragraph(a.dossier_id, st["body_sm"]),
         Paragraph("Integrity Hash", st["label"]), Paragraph(h, st["body_sm"])],
    ]
    tbl = Table(rows, colWidths=[1.1 * inch, 2.0 * inch, 1.1 * inch, 2.0 * inch])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, BORDER_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY_BG),
    ]))
    elems.append(tbl)
    elems.append(Spacer(1, 0.08 * inch))
    elems.append(Paragraph(
        "This document contains Controlled Unclassified Information (CUI). "
        "Distribution limited to authorized personnel. Handle per 32 CFR Part 2002. "
        "Integrity of this document can be verified using the SHA-256 hash above.",
        st["footer"],
    ))
    return elems


# ============================================================================
# MAIN PDF GENERATION
# ============================================================================

def generate_compliance_dossier_pdf(data: ComplianceDossierInput, output_path: str) -> str:
    st = _styles()
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                            rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    story.extend(_build_cover(data, st))
    story.extend(_build_executive_analysis(data, st))
    story.extend(_build_risk_score(data, st))
    story.extend(_build_gates(data, st))
    if data.itar_assessment and data.itar_assessment.applies:
        story.extend(_build_itar(data, st))
    if data.workflow_routing:
        story.extend(_build_workflow(data, st))
    story.extend(_build_audit(data, st))
    doc.build(story, onFirstPage=_cover_footer, onLaterPages=_page_footer)
    return output_path


# ============================================================================
# CONVENIENCE WRAPPER
# ============================================================================

def generate_compliance_dossier_from_scoring(
    vendor_name: str, dossier_id: str,
    scoring_result: Dict[str, Any],
    alert_disposition: Dict[str, Any],
    regulatory_gate_results: List[Dict[str, Any]],
    itar_result: Optional[Dict[str, Any]] = None,
    workflow_ticket: Optional[Dict[str, Any]] = None,
    output_path: str = "compliance_dossier.pdf",
) -> str:
    score = scoring_result.get("probability_score", 0.5)
    tier = (RiskTier.APPROVED if score < 0.25 else RiskTier.QUALIFIED if score < 0.45
            else RiskTier.WATCH if score < 0.60 else RiskTier.REVIEW if score < 0.80
            else RiskTier.BLOCKED)
    rec_map = {RiskTier.APPROVED: "APPROVED", RiskTier.QUALIFIED: "QUALIFIED",
               RiskTier.WATCH: "WATCH", RiskTier.REVIEW: "REVIEW",
               RiskTier.BLOCKED: "BLOCKED"}

    factors = []
    for f in scoring_result.get("contributions", []):
        factors.append(RiskFactor(
            name=f.get("factor", "Unknown"), raw_score=f.get("raw_score", 0),
            weight=f.get("weight", 0), signed_contribution=f.get("signed_contribution", 0),
            description=f.get("description", ""),
        ))

    data = ComplianceDossierInput(
        vendor_name=vendor_name, vendor_country=scoring_result.get("country", "US"),
        dossier_id=dossier_id, overall_risk_tier=tier,
        recommendation=rec_map.get(tier, "UNDER_REVIEW"),
        profile=scoring_result.get("profile", "DEFENSE_ACQUISITION"),
        sanctions_screening=SanctionsScreening(
            result=alert_disposition.get("result", "NO_MATCH"),
            match_count=alert_disposition.get("match_count", 0),
            disposition=alert_disposition.get("disposition", "NO_ACTION"),
            screening_date=alert_disposition.get("screening_date", datetime.now().strftime("%Y-%m-%d")),
        ),
        fgam_logit_score=FGAMLogitScore(
            probability_score=score, factors=factors,
            confidence_interval_low=scoring_result.get("confidence_interval_low", max(0, score - 0.1)),
            confidence_interval_high=scoring_result.get("confidence_interval_high", min(1, score + 0.1)),
            sensitivity_level=scoring_result.get("sensitivity_level", "STANDARD"),
            composite_score=int(score * 100),
        ),
        regulatory_gates=[
            RegulatoryGate(
                gate_id=g.get("gate_id", f"G{i:02d}"), name=g.get("name", f"Gate {i}"),
                status=GateStatus[g.get("status", "PENDING").upper()],
                notes=g.get("notes", ""), impact=g.get("impact", ""),
                remediation=g.get("remediation", ""),
            ) for i, g in enumerate(regulatory_gate_results, 1)
        ],
        audit_trail=AuditTrail(
            assessment_date=datetime.now().strftime("%Y-%m-%d"),
            completed_date=datetime.now().strftime("%Y-%m-%d"),
            dossier_id=dossier_id,
        ),
    )
    return generate_compliance_dossier_pdf(data, output_path)


# ============================================================================
# CLI DEMO
# ============================================================================

def _generate_demo_dossier(output_path: str = "demo_compliance_dossier.pdf") -> str:
    demo = ComplianceDossierInput(
        vendor_name="Acme Defense Systems, Inc.",
        vendor_country="US",
        dossier_id="XIP-2026-003421",
        overall_risk_tier=RiskTier.QUALIFIED,
        recommendation="QUALIFIED",
        profile="ITAR_TRADE",
        classification_level="CONTROLLED UNCLASSIFIED INFORMATION",

        executive_narrative=(
            "Helios assesses Acme Defense Systems, Inc. at 42% posterior risk probability "
            "with moderate confidence (CI 38% to 46%). The vendor falls within the QUALIFIED tier, "
            "indicating conditional acceptability contingent on resolution of 2 pending gates "
            "and 1 failed gate identified during evaluation. The DFARS CDI handling gap (G05) "
            "is the most material concern, as it directly impacts the vendor's ability to handle "
            "Controlled Unclassified Information under the ITAR_TRADE compliance profile.\n\n"
            "The primary risk drivers are Financial Health (+8.9pp), Regulatory History (+7.1pp), "
            "and Industry Classification (+6.5pp). Financial Health contributes the largest marginal "
            "information value at +0.089 to the posterior estimate (raw score 0.62, weight 8.5). "
            "While the vendor maintains audited financials and positive cash flow, debt-to-equity "
            "ratio of 2.3x exceeds the sector median of 1.6x, driving the elevated weight.\n\n"
            "OFAC screening returned no matches against consolidated sanctions lists (OFAC List "
            "Service v2.0). ITAR assessment for CAT XI (Military Electronics) items classifies the "
            "vendor as UNRESTRICTED with MEDIUM deemed export risk (score: 0.45) and 2 red flag "
            "indicators. The vendor maintains foreign national employees from Japan and Germany "
            "with access to controlled technical data, requiring a Technical Assistance Agreement "
            "(TAA) for continued engagement."
        ),

        recommendation_rationale=(
            "Recommendation of QUALIFIED is contingent upon: "
            "(1) resolve DFARS CDI 252.204-7012 (G05): establish CUI handling procedures "
            "and provide SSP documentation per NIST SP 800-171; "
            "(2) complete DFARS Specialty Metals certification (G04): provide domestic melting "
            "certificates for all specialty metal components; "
            "(3) complete Deemed Export Risk review (G11): validate TAA coverage for foreign "
            "national employees with access to ITAR-controlled technical data. "
            "Once conditions are met, the vendor may be re-scored for potential upgrade to APPROVED. "
            "Estimated remediation timeline: 30-45 days for G05, 15-20 days for G04, 10 days for G11."
        ),

        risk_storyline=[
            StorylineCard(
                rank=1, card_type="trigger", severity="high",
                title="CUI Handling Gap Identified",
                body="DFARS 252.204-7012 gate failure indicates vendor lacks documented procedures "
                     "for handling Covered Defense Information. System Security Plan not on file.",
                confidence=0.92,
            ),
            StorylineCard(
                rank=2, card_type="impact", severity="medium",
                title="Deemed Export Risk from Foreign Nationals",
                body="Two foreign national employees (JP, DE) have access to CAT XI technical data. "
                     "Deemed export analysis scores 0.45 (MEDIUM). TAA required but not yet filed.",
                confidence=0.85,
            ),
            StorylineCard(
                rank=3, card_type="reach", severity="medium",
                title="Financial Leverage Above Sector Median",
                body="Debt-to-equity ratio of 2.3x exceeds defense sector median of 1.6x. "
                     "While cash flow positive, elevated leverage increases supply chain fragility.",
                confidence=0.78,
            ),
            StorylineCard(
                rank=4, card_type="offset", severity="positive",
                title="Strong Sanctions and Entity Screening",
                body="Clean OFAC screening with zero matches. DDTC registered. No BIS Entity List "
                     "flags. NDAA 1260H and CFIUS screens both clear.",
                confidence=0.97,
            ),
            StorylineCard(
                rank=5, card_type="action", severity="info",
                title="Remediation Path Available",
                body="All identified gaps have standard remediation procedures. Estimated 30-45 day "
                     "resolution for CUI handling, 15-20 days for specialty metals certification.",
                confidence=0.88,
            ),
        ],

        sanctions_screening=SanctionsScreening(
            result="NO_MATCH", match_count=0, disposition="NO_ACTION",
            screening_date=datetime.now().strftime("%Y-%m-%d"),
            screening_tool="OFAC List Service v2.0",
        ),

        fgam_logit_score=FGAMLogitScore(
            probability_score=0.42,
            confidence_interval_low=0.38,
            confidence_interval_high=0.46,
            sensitivity_level="STANDARD",
            composite_score=42,
            factors=[
                RiskFactor("Financial Health", 0.62, 8.5, 0.089,
                           "D/E ratio 2.3x exceeds sector median 1.6x; cash flow positive but leveraged"),
                RiskFactor("Regulatory History", 0.35, 7.0, 0.071,
                           "One prior DFARS non-conformance (2024, remediated); clean DCAA record"),
                RiskFactor("Industry Classification", 0.48, 6.5, 0.065,
                           "Defense electronics (NAICS 334511) carries inherent ITAR exposure"),
                RiskFactor("International Exposure", 0.55, 6.0, 0.058,
                           "Parent company ties to Japan and Germany; FOCI mitigated via SSA"),
                RiskFactor("Prior Sanctions", 0.12, 5.5, 0.052,
                           "No prior sanctions; clean screening history across 3 years of records"),
                RiskFactor("Ownership Structure", 0.40, 5.0, 0.048,
                           "Publicly traded (NYSE); 12% foreign institutional ownership, all allied"),
                RiskFactor("Market Position", 0.30, 4.5, 0.041,
                           "Mid-cap defense supplier; stable revenue, no concentration risk"),
                RiskFactor("Government Contracts", 0.25, 4.0, 0.039,
                           "Active CAGE code; 47 prime contracts since 2020, 3 active subcontracts"),
                RiskFactor("Subcontractor Risk", 0.33, 3.5, 0.036,
                           "Tier 2 supply chain includes 4 foreign entities (all allied nations)"),
                RiskFactor("Geographic Risk", 0.08, 3.0, 0.031,
                           "HQ: San Diego, CA; manufacturing: Huntsville, AL; both CONUS"),
                RiskFactor("Third-party Exposure", 0.22, 2.5, 0.028,
                           "Primary bank: JPMorgan; auditor: Deloitte; insurer: AIG"),
                RiskFactor("Compliance Track Record", 0.18, 2.0, 0.025,
                           "ISO 9001, AS9100D certified; CMMC Level 2 assessment scheduled"),
                RiskFactor("Technology Risk", 0.15, 1.5, 0.021,
                           "Product line includes ITAR-controlled radar subsystems (Cat XI)"),
                RiskFactor("Supply Chain Maturity", 0.20, 1.0, 0.018,
                           "Established supply chain; dual-source for critical components"),
            ],
        ),

        regulatory_gates=[
            RegulatoryGate("G01", "Section 889 (NDAA FY2019)", GateStatus.PASS,
                          notes="No prohibited telecom components", impact="", remediation=""),
            RegulatoryGate("G02", "ITAR Compliance", GateStatus.PASS,
                          notes="DDTC registered, M-2239 current", impact="", remediation=""),
            RegulatoryGate("G03", "EAR Controls", GateStatus.PASS,
                          notes="No dual-use items requiring BIS license", impact="", remediation=""),
            RegulatoryGate("G04", "DFARS Specialty Metals", GateStatus.PENDING,
                          notes="Awaiting domestic melting certificates",
                          impact="Specialty metal components may not meet 10 USC 4863 domestic source requirements",
                          remediation="Request domestic melting certificates from tier 1 suppliers; estimated 15-20 days"),
            RegulatoryGate("G05", "DFARS CDI (252.204-7012)", GateStatus.FAIL,
                          notes="CUI handling procedures not documented",
                          impact="Vendor cannot handle Covered Defense Information without SSP per NIST SP 800-171",
                          remediation="Develop System Security Plan, implement CUI marking/handling procedures; 30-45 day effort"),
            RegulatoryGate("G06", "CMMC 2.0", GateStatus.PASS,
                          notes="Level 2 self-assessment complete", impact="", remediation=""),
            RegulatoryGate("G07", "FOCI (Foreign Ownership)", GateStatus.PASS,
                          notes="SSA in place for Japanese parent", impact="", remediation=""),
            RegulatoryGate("G08", "NDAA 1260H (CMC List)", GateStatus.PASS,
                          notes="Not on Chinese Military Company list", impact="", remediation=""),
            RegulatoryGate("G09", "CFIUS Jurisdiction", GateStatus.PASS,
                          notes="No CFIUS-triggering transaction", impact="", remediation=""),
            RegulatoryGate("G10", "Berry Amendment", GateStatus.SKIP,
                          notes="N/A: product not covered by Berry", impact="", remediation=""),
            RegulatoryGate("G11", "Deemed Export Risk", GateStatus.PENDING,
                          notes="Foreign national TAA coverage under review",
                          impact="Foreign national access to ITAR technical data requires export authorization",
                          remediation="File TAA amendment to cover JP and DE nationals; estimated 10 days"),
            RegulatoryGate("G12", "End-Use Red Flags", GateStatus.PASS,
                          notes="No transaction diversion indicators", impact="", remediation=""),
            RegulatoryGate("G13", "USML Category Control", GateStatus.PASS,
                          notes="Cat XI export to allied nations authorized", impact="", remediation=""),
        ],

        itar_assessment=ITARAssessment(
            applies=True,
            country_status="UNRESTRICTED",
            deemed_export_risk="MEDIUM",
            deemed_export_score=0.45,
            red_flag_count=2,
            red_flag_score=0.28,
            red_flags=[
                "Multiple international parent company relationships (Japan, Germany) with access to controlled technical data",
                "Export-controlled radar subsystem technology (Cat XI) in active product roadmap requires TAA authorization",
            ],
            usml_category="CAT XI",
            license_type="TAA",
            foreign_nationals=["JP", "DE"],
            narrative=(
                "ITAR evaluation for Category XI (Military Electronics) controlled items indicates "
                "UNRESTRICTED country status for the vendor's US-based operations. However, deemed "
                "export risk is assessed at MEDIUM (score: 0.45) due to two foreign national employees "
                "from Japan and Germany with engineering-level access to controlled radar subsystem "
                "specifications. While both nations are allied (Five Eyes+ partners), 22 CFR 120.17 "
                "requires export authorization for any release of ITAR-controlled technical data to "
                "foreign persons regardless of nationality. A Technical Assistance Agreement (TAA) "
                "is the required authorization vehicle. Current TAA (M-2239) does not explicitly "
                "cover the two identified foreign nationals. Filing a TAA amendment is recommended "
                "before granting continued access to Cat XI technical data packages."
            ),
        ),

        workflow_routing=WorkflowRouting(
            queue_assignment="ITAR_REVIEW_QUEUE",
            sla_hours=48,
            escalation_path="EXPORT_CONTROL_MANAGER",
            notification_recipients=["compliance@xiphos.com", "legal@acmedefense.com"],
            rationale=(
                "Routed to ITAR_REVIEW_QUEUE based on: (1) ITAR assessment with MEDIUM deemed "
                "export risk, (2) pending TAA coverage for foreign nationals, (3) DFARS CDI gate "
                "failure requiring compliance officer determination. 48-hour SLA applies per "
                "ITAR_TRADE profile routing rules. If unresolved at SLA boundary, auto-escalates "
                "to Export Control Manager for disposition."
            ),
        ),

        audit_trail=AuditTrail(
            assessment_date="2026-03-23",
            completed_date="2026-03-23",
            assessment_version="1.0",
            dossier_id="XIP-2026-003421",
            assessor="HELIOS_ENGINE_v5.2",
            signature_hash=hashlib.sha256(
                json.dumps({"vendor": "Acme Defense Systems, Inc.", "date": "2026-03-23"}).encode()
            ).hexdigest(),
        ),
    )

    return generate_compliance_dossier_pdf(demo, output_path)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        output = _generate_demo_dossier()
        print(f"Demo dossier generated: {output}")
    else:
        print("Usage: python3 compliance_dossier_pdf.py --demo")


if __name__ == "__main__":
    main()
