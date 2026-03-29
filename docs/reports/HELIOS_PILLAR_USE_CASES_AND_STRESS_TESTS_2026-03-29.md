# Helios Pillar Use Cases And Stress Tests

Generated: 2026-03-29

## Pillar Frame

Helios should brief clients and stress itself against three adversary-shaped pillars:

1. `Supply Chain Vetting & Assurance`
2. `Cyber Supply Chain Assurance`
3. `Customs, Export, and Trade Evasion Expertise`

This framing is stronger than generic lane language because it maps to real threat behavior:
- adversaries hide behind ownership layers, intermediaries, nominees, and low-substance entities
- adversaries use vendors, products, update paths, and service providers as cyber access routes
- adversaries route controlled, restricted, or tainted goods through intermediaries, false origin stories, and opaque end-use narratives

## Official Source Basis

- DCSA Section 847 and FOCI implementation emphasize ownership, control, and influence before award: [DCSA Section 847](https://www.dcsa.mil/Section847/), [DCSA FOCI Action Planning](https://www.dcsa.mil/Industrial-Security/Entity-Vetting-Facility-Clearances-FOCI/Foreign-Ownership-Control-or-Influence/FOCI-Action-Planning-Implementation/)
- OFAC requires indirect ownership reasoning through layered entities and distinguishes ownership from control: [OFAC FAQ 401](https://ofac.treasury.gov/faqs/401), [OFAC FAQ 398](https://ofac.treasury.gov/faqs/398)
- FinCEN highlights shells, nominees, and opacity as financial-crimes concealment mechanisms, and as of March 2025 removed BOI reporting requirements for U.S. companies and U.S. persons: [FinCEN shell-company advisory](https://www.fincen.gov/sites/default/files/shared/AdvisoryOnShells_FINAL.pdf), [FinCEN March 2025 BOI change](https://www.fincen.gov/news/news-releases/fincen-removes-beneficial-ownership-reporting-requirements-us-companies-and-us)
- NIST and CISA define cyber supply-chain risk as product, provenance, dependency, update-path, and operational-trust risk, not just CVE counting: [NIST SP 800-161 Rev. 1](https://csrc.nist.gov/pubs/sp/800/161/r1/upd1/final), [CISA Secure by Design](https://www.cisa.gov/securebydesign), [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog), [NIST SP 800-171 Rev. 3](https://csrc.nist.gov/pubs/sp/800/171/r3/final)
- BIS, FinCEN, and CBP highlight transshipment, end-user ambiguity, customs fraud, origin fraud, and forced-labor screening as real evasion patterns: [BIS Red Flags](https://www.bis.gov/enforcement/identify-red-flags), [FinCEN/BIS joint notice](https://www.bis.gov/media/documents/fincenjointnoticeusexportcontrolsfinal508.pdf), [CBP UFLPA](https://www.cbp.gov/trade/forced-labor/UFLPA), [CBP trade violations](https://www.cbp.gov/trade/e-allegations/violations)

## Pillar Scenarios

### Supply Chain Vetting & Assurance

#### 1. Hidden Foreign Influence In A Domestic Defense Supplier
- Adversary objective: win work through a nominally domestic supplier while retaining upstream foreign influence through equity, veto rights, debt, or board leverage
- Client question: can we award or retain this supplier if the public-facing story is domestic but the control story is not
- Helios must prove:
  - whether beneficial ownership is actually known
  - whether control exists without full ownership visibility
  - whether layered foreign influence changes award posture

#### 2. Shell / Nominee Pass-Through Subcontractor
- Adversary objective: use a low-substance shell, nominee officers, or shared-agent pass-through to mask the real operator
- Client question: is this a real operating supplier or a concealment vehicle
- Helios must prove:
  - whether the entity has substance
  - whether intermediaries, agents, or banking paths imply hidden control
  - whether opacity is normal private-company behavior or concealment risk

#### 3. Lower-Tier Supplier With Concealed Dependency
- Adversary objective: stay invisible at the prime level while owning or controlling a critical lower-tier node
- Client question: does lower-tier opacity materially change the trust posture of the prime
- Helios must prove:
  - the real dependency chain
  - whether critical subsystems depend on concealed lower-tier actors
  - whether tier-2 or tier-3 trust should alter top-line approval

### Cyber Supply Chain Assurance

#### 4. KEV-Rich Product In A Sensitive Environment
- Adversary objective: gain access through a vulnerable product deployed in a mission or CUI environment
- Client question: is the supplier acceptable when the product line overlaps with actively exploited vulnerabilities
- Helios must prove:
  - whether the exposure is real and current
  - whether compensating evidence exists
  - whether mission criticality changes the disposition

#### 5. Secure-By-Design Marketing Without Artifact Proof
- Adversary objective: sell a trust story without SBOM, VEX, provenance, or remediation evidence
- Client question: can we trust a supplier who markets maturity but cannot evidence it
- Helios must prove:
  - whether claims are artifact-backed
  - whether missing provenance or SBOM evidence is material
  - whether marketing-only secure-by-design claims should survive scrutiny

#### 6. Compromised Update / Signing / MSP Path
- Adversary objective: compromise the supplier through a shared signing service, fourth-party MSP, or fragile update path
- Client question: does the real risk sit behind the supplier in the fourth-party chain
- Helios must prove:
  - whether update or signing monoculture exists
  - whether fourth-party concentration changes posture
  - whether direct supplier evidence hides a deeper dependency problem

### Customs, Export, and Trade Evasion Expertise

#### 7. Third-Country Transshipment To Hide End User Or Origin
- Adversary objective: disguise the true end user, true destination, or true country of origin through a reseller or broker chain
- Client question: is this ordinary distribution or evasion
- Helios must prove:
  - whether intermediary handling is bounded or opaque
  - whether final country or end user is unresolved
  - whether the route changes the export or customs posture

#### 8. Deemed Export Inside U.S. Operations
- Adversary objective: obtain controlled technical access inside the United States through foreign-person repo, VPN, or remote support access
- Client question: is this a domestic workflow or an export event
- Helios must prove:
  - whether foreign-person access is real
  - whether TCP or TTCP controls exist
  - whether support language is masking technical-data release

#### 9. Dual-Use Component In Sensitive End Use
- Adversary objective: exploit a seemingly low-friction classification while hiding a sensitive end use or program context
- Client question: does the narrative around the end use force escalation even if rules alone look permissive
- Helios must prove:
  - whether classification confidence is enough
  - whether end-use ambiguity is material
  - whether allied geography is hiding a sensitive mission context

## Cross-Pillar Scenarios

#### 10. Foreign-Influenced Software Vendor On A Sensitive Program
- Pillars: supply chain vetting + cyber supply chain assurance
- Adversary objective: gain privileged software or admin access through a supplier whose control chain is opaque or foreign-influenced

#### 11. Opaque Distributor Moving Dual-Use Components Through Third Countries
- Pillars: supply chain vetting + customs/export
- Adversary objective: combine hidden ownership with transshipment and broker opacity to move sensitive goods through plausible commercial cover

#### 12. Clean Prime, Dirty Tier-2
- Pillars: all three
- Adversary objective: hide the real operational risk below the prime through lower-tier ownership opacity, cyber weakness, and export-routing risk

## Ranking Matrix

Scoring scale: `5 = highest`

| Rank | Scenario | Buyer Relevance | Demo Impact | Technical Stress | Fixture Ready | End-to-End Ready |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | Hidden Foreign Influence In A Domestic Defense Supplier | 5 | 5 | 5 | yes | yes |
| 2 | Foreign-Influenced Software Vendor On A Sensitive Program | 5 | 5 | 5 | no | no |
| 3 | Clean Prime, Dirty Tier-2 | 5 | 5 | 5 | no | no |
| 4 | Third-Country Transshipment To Hide End User Or Origin | 5 | 5 | 4 | yes | yes |
| 5 | KEV-Rich Product In A Sensitive Environment | 5 | 4 | 5 | yes | yes |
| 6 | Deemed Export Inside U.S. Operations | 5 | 4 | 5 | yes | no |
| 7 | Shell / Nominee Pass-Through Subcontractor | 4 | 5 | 4 | yes | no |
| 8 | Opaque Distributor Moving Dual-Use Components Through Third Countries | 4 | 5 | 5 | no | no |
| 9 | Compromised Update / Signing / MSP Path | 5 | 4 | 4 | yes | no |
| 10 | Secure-By-Design Marketing Without Artifact Proof | 4 | 4 | 4 | yes | no |
| 11 | Lower-Tier Supplier With Concealed Dependency | 4 | 4 | 4 | yes | no |
| 12 | Dual-Use Component In Sensitive End Use | 4 | 4 | 4 | yes | yes |

## Top 9 Replayable Fixture Set

These nine are the current replayable adversarial packs because they map cleanly onto existing Helios fixture harnesses:

### Supply Chain Vetting & Assurance
- Hidden Foreign Influence In A Domestic Defense Supplier
- Shell / Nominee Pass-Through Subcontractor
- Lower-Tier Supplier With Concealed Dependency

Fixture: [pillar_supply_chain_vetting_assurance_cases.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/adversarial_gym/pillar_supply_chain_vetting_assurance_cases.json)

### Cyber Supply Chain Assurance
- KEV-Rich Product In A Sensitive Environment
- Secure-By-Design Marketing Without Artifact Proof
- Compromised Update / Signing / MSP Path

Fixture: [pillar_cyber_supply_chain_assurance_cases.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/adversarial_gym/pillar_cyber_supply_chain_assurance_cases.json)

### Customs, Export, and Trade Evasion Expertise
- Third-Country Transshipment To Hide End User Or Origin
- Deemed Export Inside U.S. Operations
- Dual-Use Component In Sensitive End Use

Fixture: [pillar_customs_export_trade_evasion_cases.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/adversarial_gym/pillar_customs_export_trade_evasion_cases.json)

## Four End-To-End Dossier Scenarios

These four are the current full query-to-dossier audit set because Helios can render them through the current live dossier path without inventing unsupported evidence:

1. Yorktown descriptor-only ownership evidence
2. Hidden-owner counterparty trust case
3. Cyber supply chain assurance review
4. Export transshipment / trade review

Pack: [pillar_briefing_query_to_dossier_pack.json](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/fixtures/customer_demo/pillar_briefing_query_to_dossier_pack.json)

## Pass / Fail Standard

Every scenario should force Helios to answer:
- who owns it
- who controls it
- who influences it
- what the adversary is exploiting
- what remains unresolved

A scenario fails if Helios:
- invents a named owner from descriptor text
- collapses control into ownership
- misses the workflow lane or posture implied by the scenario
- emits dossier artifacts with upstream error text, stale template placeholders, or contradictory conclusions
- produces a dossier that omits the pillar-specific reason the case matters
