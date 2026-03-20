# XIPHOS HELIOS | LinkedIn Drip Campaign
## 5-Post Sequence (2 weeks)

---

## POST 1 (Day 1) — Entity Resolution
**Theme: "Who is this vendor, really?"**

The most fundamental question in defense supply chain vetting is also the one most often skipped.

When a contracting officer receives a bid from "Smith Defense Solutions LLC," what do they actually know? A name. Maybe a CAGE code. Maybe a self-certified SDVOSB status.

What they don't know: Who owns it. Who owned it last year. Whether it shares a parent company with a FARA-registered foreign agent. Whether its ultimate beneficial owner sits in an allied nation or an adversary state.

We built Helios to answer that question first.

Before a single screening connector fires, Helios resolves the entity across five authoritative registries in parallel: SAM.gov (UEI, CAGE, corporate ownership chain, SBA certifications), SEC EDGAR (CIK, ticker, public filings), GLEIF (LEI, parent chains), OpenCorporates (200M+ companies across 200 jurisdictions), and Wikidata (founding year, HQ, parent company).

The result: a disambiguated, cross-referenced entity profile with every known identifier resolved. Not a name match. Not a keyword search. A verified identity.

Because you can't vet what you can't identify.

#EntityResolution #DefenseAcquisition #SupplyChainSecurity #FOCI #VendorVetting

---

## POST 2 (Day 4) — OSINT Sources & Source Reliability
**Theme: "Not all data is created equal"**

A sanctions hit from the US Treasury's OFAC SDN list and an adverse headline from a Google News RSS scrape are not the same thing.

But most vetting tools treat them identically. A "finding" is a "finding." A red flag is a red flag. No distinction between a government primary source and a media aggregator.

Helios assigns every OSINT connector a reliability weight based on source authority:

Authoritative (0.90-0.95): OFAC SDN, Trade.gov CSL, UN Sanctions, SAM.gov Exclusions, EU CFSP, UK HMT/OFSI
High (0.80-0.85): SEC EDGAR, GLEIF, World Bank Debarment, CourtListener, USAspending
Medium (0.60-0.70): OpenCorporates, ICIJ Offshore Leaks
Low (0.45-0.50): GDELT, Google News

These weights flow directly into scoring. A finding from an authoritative source carries more weight than a dozen media hits. And only sources with reliability above 0.80 can trigger hard-stop escalations.

27 live sources. Zero simulated data. Every finding traced to its origin.

Provenance matters when the stakes are national security.

#OSINT #SourceReliability #DataProvenance #DefenseIndustrialBase #Compliance

---

## POST 3 (Day 7) — Scoring Engine
**Theme: "Risk isn't binary. Your scoring shouldn't be either."**

Pass/fail checklists don't work for defense supply chain risk.

A Tier 2 subcontractor providing commercial off-the-shelf components does not require the same scrutiny as a vendor delivering subsystems for a Special Access Program. A US-headquartered public company with 20 years of federal contracts carries different risk than a newly formed LLC with a foreign parent entity in a non-allied nation.

Helios scores through a 14-factor model calibrated across seven sensitivity tiers, from CRITICAL_SAP to COMMERCIAL.

The factors: sanctions proximity, geographic risk, ownership opacity, data quality coverage, executive PEP exposure, regulatory gate compliance, ITAR exposure, EAR control status, foreign ownership depth, CMMC readiness, single-source risk, geopolitical sector exposure, financial stability, and compliance history.

Each factor weighted by program sensitivity. Each contribution traceable to its source. And a Wilson confidence interval that widens when data comes from low-reliability sources and narrows when backed by authoritative government records.

The output: not a binary pass/fail, but a calibrated probability with a tier classification, factor-by-factor contributions, and a confidence range.

Because nuance is the difference between catching risk and creating noise.

#RiskScoring #DefenseCompliance #CMMC #SupplyChainRisk #Xiphos

---

## POST 4 (Day 10) — Contract Vehicle Search & Supply Chain Mapping
**Theme: "See the entire supply chain. Not just the prime."**

When a program office awards a task order under OASIS, they know who the prime contractor is. But what about the prime's subcontractors? Their sub-subcontractors? The small businesses providing specialty components three tiers deep?

That's where adversaries target. The long tail. The vendors nobody's watching.

Helios includes a contract vehicle search workflow powered by USAspending.gov. Type "OASIS" and see the strongest vehicle-linked prime and subcontractor matches available from public award data, with award amounts, awarding agencies, and relationship mapping.

The results render as an interactive award relationship graph: gold node for the searched vehicle family, blue nodes for primes, amber nodes for subcontractors. Lines trace the prime-to-sub relationships. Click any node to create a case and launch a full assessment.

And when you need to vet the discovered entities in bulk, the vehicle batch action creates scored draft cases for every vendor recovered from the search results. Analysts can then run the full 27-connector enrichment flow per case where deeper review is warranted.

One click. Full supply chain visibility.

#SupplyChainMapping #ContractVehicle #OASIS #DefenseAcquisition #SubcontractorRisk

---

## POST 5 (Day 14) — Corporate Ownership & FOCI
**Theme: "The 12-month clock is ticking."**

The FY2026 NDAA gives DoD 12 months to implement a formal vetting framework for foreign ownership, control, and influence. The era of self-certification is ending.

Helios was built for this moment.

When SAM.gov returns an entity with a corporate ownership chain, Helios renders it as a visual ownership tree: Ultimate Parent, Immediate Parent, Subject Entity. Each node shows the entity name, country, and CAGE code. Foreign owners are color-coded: green for domestic, amber for allied nations (Five Eyes, NATO, key partners), red for non-allied or adversary states.

This isn't inferred. It's pulled directly from SAM.gov's integrity information section: the highest owner, immediate owner, predecessors, and country of incorporation. The same data DCSA uses for FOCI determinations.

And the scoring engine takes it from there. Foreign ownership from an allied nation carries a different weight than foreign ownership from an adversary state. The model accounts for the difference. Automatically. At scale.

300,000 companies in the defense industrial base. 12 months to build the infrastructure. The clock started.

We're ready.

xiphosllc.com

#FOCI #NDAA2026 #CorporateOwnership #DefenseIndustrialBase #NationalSecurity #Xiphos
