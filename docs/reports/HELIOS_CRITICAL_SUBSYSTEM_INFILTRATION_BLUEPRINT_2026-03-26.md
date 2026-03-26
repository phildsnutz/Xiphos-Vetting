# Helios Critical Subsystem Infiltration Blueprint

Date: 2026-03-26
Scenario bias: F-35 style critical subsystem compromise through an obscured tier-3 or tier-4 supplier with hostile-state control

## Thesis

The next Helios expansion should target the hidden component path, not the obvious prime.

The product story is not:

- `Prime contractor is risky`

The product story is:

- `mission-critical subsystem`
- `integrator`
- `subsystem vendor`
- `component or board supplier`
- `specialty electronics or firmware shop`
- `foreign-owned parent / hidden holding company / sanctioned affiliate`

That is where Helios can become genuinely differentiated.

## Threat Model

Representative failure pattern:

1. A critical assembly in a high-value weapons or aircraft program depends on a small electronic, cyber-relevant, or control-system component.
2. That component comes from a tier-2 to tier-4 vendor outside the main procurement spotlight.
3. The vendor appears benign at the surface layer.
4. Ownership, beneficial control, distributor structure, or offshore holding relationships conceal PLA-linked or hostile-state influence.
5. The component creates reliability, kill-switch, telemetry, firmware, sabotage, or maintenance-channel risk.

This means the next Helios cohort should be selected for:

- electronics exposure
- control-system exposure
- firmware or network exposure
- sub-tier supply chain position
- ownership opacity
- foreign control or enforcement adjacency

## Entity Bias

The next cohort should favor these company classes:

1. Embedded electronics and avionics boards
2. RF modules, antennas, filters, timing, and comms subsystems
3. Sensors, inertial measurement units, navigation components, and control electronics
4. Power modules, batteries, converters, and specialty power management vendors
5. Actuators, valves, servo controls, harnesses, connectors, and control assemblies
6. PCB, EMS, contract manufacturing, and specialty machining firms touching critical assemblies
7. Firmware, secure boot, telemetry, edge compute, and ruggedized embedded-system vendors
8. Specialty distributors, brokers, and resellers sitting between maker and integrator
9. Offshore parent, holding, and affiliate entities around the above firms

Avoid over-spending the next cohort on:

- giant primes already visible everywhere
- generic services shops with no product or component footprint
- low-signal trade show brands that do not map to a physical or firmware-relevant part

## Next Cohort Shape

Recommended next targeted cohort: `500` entities

1. `180` US sub-tier electronics and component suppliers
   - embedded boards
   - avionics electronics
   - sensors
   - RF and power modules
   - connectors, harnesses, control assemblies

2. `120` contract manufacturers, specialty machining houses, and integration shops
   - PCB / EMS
   - board assembly
   - precision component manufacturing
   - test and calibration houses

3. `100` foreign-linked parents, affiliates, distributors, or beneficial-control entities
   - China, Hong Kong, Singapore, UAE, Turkey, Serbia, Cyprus, offshore shells
   - only where there is plausible linkage into the component chain

4. `60` cyber-adjacent vendors
   - firmware
   - embedded security
   - rugged networking
   - update / telemetry / edge appliance vendors

5. `40` targeted persons
   - founders
   - UBOs
   - directors
   - export-control officers
   - beneficial owners tied to categories 1 to 3

Brutal truth:
This `500` is higher value than another generic `1000`.

## Source Priority

The source stack for this scenario should be ordered around supply-chain explainability:

1. `sam_subaward_reporting`
   - best current path into lower-tier US subcontractors
   - highest immediate ROI for tier-2 to tier-4 mapping

2. `usaspending`
   - prime-to-recipient relationships
   - supplier adjacency and contract lineage

3. `fpds_contracts`
   - procurement context and award history

4. `sec_edgar`
   - public-company subsidiary and ownership structure

5. `gleif_lei`
   - legal-entity normalization across parent and affiliate structures

6. `opencorporates`
   - global corporate linkages for shell and affiliate expansion

7. `uk_companies_house`
   - UK beneficial ownership and filings where relevant

8. `trade_csl`, `ofac_sdn`, `opensanctions_pep`, `worldbank_debarred`
   - hard-stop and beneficial-owner pressure

9. `cisa_kev` and `nvd_overlay`
   - cyber relevance for products, firmware exposure, and exploited technologies

10. `gdelt_media` and `google_news`
    - only as supporting evidence, not primary selection logic

## Collector Changes

Highest-ROI collector additions for this threat model:

1. A `component_vendor_fixture`
   - replayable seed list of defense electronics, actuator, connector, RF, and embedded vendors
   - grouped by subsystem class and criticality
   - local-first and fixture-driven, consistent with current collector posture

2. A `subtier_supply_chain_fixture`
   - curated prime -> subsystem -> component supplier chains
   - starts with a small number of demonstrator paths
   - ideal for fixture-driven graph development before broader live automation

3. A public `electronics_distributor_html` collector
   - public product-line pages
   - line card pages
   - authorized distributor vendor lists
   - no login, no anti-bot games

4. A `cage_uei_resolution_enricher`
   - improve low-tier identity resolution where brand and legal entity diverge

## Graph Model Upgrades

Helios should add or strengthen these node and edge concepts:

New or formalized entity types:

- `product_family`
- `component`
- `subsystem`
- `distributor`
- `contract_manufacturer`
- `holding_company`

New or formalized relationship types:

- `supplies_component_to`
- `manufactures_for`
- `assembles_for`
- `distributed_by`
- `owned_by`
- `beneficially_owned_by`
- `firmware_used_in`
- `integrated_into`
- `maintains`
- `certifies_for`

Why this matters:

- current company-to-company edges are useful but too coarse
- the sabotage story lives in the component path
- Helios needs to explain how a risky entity reaches a mission-critical assembly, not just that the risky entity exists

## Scoring Bias Changes

The scoring layer should weight these more heavily for this scenario:

1. component criticality
2. control-system proximity
3. firmware and telemetry exposure
4. supply-chain depth into mission-critical assemblies
5. ownership opacity
6. foreign-control probability
7. sanctions or entity-list adjacency of parent or affiliate nodes

Add a scenario-specific flag:

- `critical_subsystem_infiltration_risk`

That flag should rise when Helios can form a path like:

- `critical platform`
- `subsystem integrator`
- `component vendor`
- `opaque holding company`
- `hostile-state or PLA-linked entity`

## Best Demo Story

The strongest analyst demo is not:

- `this vendor is Chinese`

The strongest analyst demo is:

- `this subsystem depends on a small US-facing component supplier`
- `that supplier resolves to an electronics shop with offshore parent ownership`
- `the parent structure links into a hostile-state influenced network`
- `the component class is cyber-relevant or mission-critical`
- `there is no clean alternative supplier concentration story`

That is a procurement and national-security product, not just a sanctions screener.

## Immediate Execution Recommendation

After the current overnight run finishes:

1. build the next `500`-entity cohort around electronics, component, and cyber-adjacent suppliers
2. create a replayable `component_vendor_fixture`
3. create a small `subtier_supply_chain_fixture` with 10 to 20 demonstrator chains
4. add component-path graph edges before adding more generic vendor volume
5. only then run a focused `40` to `100` person pass for UBOs and directors tied to the riskiest component vendors

## My Recommendation

Yes, bias hard toward cyber, electronics, supply chain, and component providers.

That is the path that gets Helios from:

- `vendor screening tool`

to:

- `critical subsystem infiltration detection tool`
