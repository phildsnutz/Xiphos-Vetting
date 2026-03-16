# Xiphos Vertical Expansion Roadmap

## Strategic Architecture: Configurable Compliance Profiles

The core thesis: ONE platform with configurable "compliance profiles" that swap out risk model weights, connector priorities, UI terminology, and workflow rules. The Bayesian engine, OSINT connector framework, AI analysis layer, decision audit trail, batch import, and RBAC are shared infrastructure.

### Profile System

| Profile | Base | Additions |
|---------|------|-----------|
| Defense Acquisition | Current Xiphos | sanctions + ownership + geography + DFARS |
| ITAR/Trade Compliance | Xiphos | + USML categories + end-use analysis + deemed export |
| University Research Security | Xiphos | + talent programs + institutional risk + research domains |
| Grants Compliance | Xiphos | + FAPIIS + Do Not Pay + sub-awardee chain |
| Commercial Supply Chain | Xiphos | + regulatory databases + continuous monitoring + ESG |

---

## 1. Supply Chain Compliance (Lowest Hanging Fruit)

**What we already have:** The defense acquisition lane IS supply chain compliance. Broadening to commercial (automotive tier-1, pharma ingredient sourcing, electronics component traceability) requires modest tweaks.

**New Connectors Needed:**
- FDA Debarment Lists
- EU REACH/RoHS substance databases
- Conflict Minerals (SEC Rule 13p-1 / Dodd-Frank 1502)

**Scoring Model Changes:**
- Add "regulatory compliance" factor alongside existing sanctions/geography/ownership factors

**UI Language Shifts:**
- Swap "weapons_system" program tiers for industry categories: "pharmaceutical API," "automotive safety-critical," "food-grade ingredient"

**New Module:**
- Continuous monitoring: re-screens vendors on schedule, alerts on changes (new sanctions, adverse media spike, corporate structure change)

**Estimated Effort:** ~2-week sprint to market-ready

---

## 2. University Research Security

**Why this market:** NSDD-189, CHIPS Act research security provisions, NSPM-33 requirements. Universities receiving federal research funding must vet foreign collaborators, visiting scholars, and subrecipient institutions for ties to foreign governments of concern, military-civil fusion entities, and talent recruitment programs.

**What we already have:**
- BIS Entity List connector catches military-civil fusion entities
- Sanctions screening catches designated individuals and organizations

**New Connectors Needed:**
- "Foreign Talent Program" connector: checks against known PRC talent recruitment databases (Thousand Talents, Changjiang Scholars, etc.)
- "Institutional Risk" scoring layer: evaluates foreign universities and research institutes (e.g., Harbin Engineering University = PLA-affiliated)
- NSF/NIH disclosure requirements integration

**UI Language Shifts:**
- "vendor" -> "collaborator"
- "program" -> "research domain" (dual-use technology areas: AI, quantum, semiconductors, hypersonics carry higher base risk)

**Target Buyer:** University research compliance offices. Market is desperately underserved (spreadsheets and manual ODNI checks).

---

## 3. Government Grants Compliance

**Overlap with existing:** Heavy. Federal grant recipients (prime and sub-awardees) must be checked against SAM.gov exclusions (have this), OFAC SDN (have via OpenSanctions), "Do Not Pay" list, debarment databases.

**New Connectors Needed:**
- USAspending.gov sub-award data (basic connector exists, needs expansion)
- FAPIIS (Federal Awardee Performance and Integrity Information System)
- GSA Excluded Parties system

**New Scoring Module:**
- "Responsible contractor" scoring: past performance ratings, active federal awards, financial stability indicators

**Target Buyer:** Federal agency grants management offices, state agencies administering federal pass-through funds, large nonprofits/universities managing hundreds of sub-awards.

**Estimated Effort:** Minimal. Existing connectors cover ~70% of need.

---

## 4. Customs/Trade Compliance with ITAR Focus (Highest Value)

**Most technically demanding but highest-value market.** ITAR compliance requires screening every party in a defense article transfer: end-user, intermediate consignees, freight forwarders, foreign sub-contractors.

### New Modules:

**A. USML Classification Module**
- Analyst inputs USML category (I through XXI) during screening
- Scoring engine weights risk factors differently by category
- Category I (firearms) has different risk patterns than Category XI (military electronics) or Category XV (spacecraft)

**B. End-Use/End-User Analysis Layer**
- Assess whether foreign party will use defense article for stated purpose or divert
- Existing country risk + ownership analysis covers most of this
- Add specific checks for:
  - Military end-use indicators
  - WMD program affiliations
  - "Red flag" behavioral patterns from BIS guidance (unusual routing, reluctance to provide end-use details, cash payment insistence)

**C. EAR Parallel Track**
- Many transactions involve "dual-use" items controlled under EAR rather than ITAR
- BIS Entity List connector is a start
- Need ECCN (Export Control Classification Number) awareness for license exception applicability

**D. Deemed Export Screening Module**
- For universities and companies hiring foreign nationals accessing controlled technology
- Connects directly to University Research Security use case

**Target Buyer:** Every defense contractor, every company with a TAA or MLA, every freight forwarder handling defense articles.

**Competitive Landscape:** Visual Compliance, Descartes, OCR Services -- all expensive and clunky. Modern AI-augmented Bayesian scoring is genuinely differentiated.

---

## Implementation Priority Order

1. **Compliance Profile Selector** (foundation for all verticals)
   - Dropdown during case creation swaps risk weights, connector priorities, UI labels
   - Profiles: Defense Acquisition, ITAR, University Research Security, Grants, Commercial Supply Chain

2. **ITAR Profile** (highest value, initial focus)
   - USML category awareness
   - End-use/end-user red flag analysis
   - Deemed export screening

3. **University Research Security Profile** (underserved market, fast build)
   - Foreign Talent Program connector
   - Institutional Risk scoring
   - Research domain risk weighting

4. **Grants Compliance Profile** (minimal effort, existing connector leverage)
   - FAPIIS connector
   - Do Not Pay integration
   - Sub-awardee chain tracking

5. **Commercial Supply Chain Profile** (broadest market)
   - FDA/REACH/RoHS connectors
   - Continuous monitoring scheduler
   - ESG risk factors

6. **Continuous Monitoring Module** (cross-cutting, applies to all profiles)
   - Scheduled re-screening (weekly/monthly cadence)
   - Alert reports on risk profile changes
   - Delta analysis (what changed since last screen)
