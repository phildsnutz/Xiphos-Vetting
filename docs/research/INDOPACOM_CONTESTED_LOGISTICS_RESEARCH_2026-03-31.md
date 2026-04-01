# INDOPACOM Contested Logistics Research

Date: March 31, 2026

## Question

What makes contested logistics uniquely hard in the USINDOPACOM area of responsibility, and how should Helios test that lane in a way that is operationally honest?

## Bottom line

INDOPACOM contested logistics is not just "long supply lines."

It is a specific operating problem made up of:

- oceanic distance and long resupply timelines
- dispersed, austere, and missile-vulnerable operating locations
- degraded port and airfield assumptions
- dependence on allied access, agreements, and interoperability
- weak in-theater maintenance and repair depth west of the International Date Line
- logistics command-and-control dependency on data, cyber, and commercial networks

Helios should not try to model route optimization first. Helios is strongest when it models the brittle supplier, repair, fuel, site, finance, service, and network dependencies that decide whether a contested sustainment concept is actually resilient.

## Key findings

### 1. Distance is the baseline problem, not the whole problem

Source-backed fact:

- The Army wrote on January 29, 2026 that the Indo-Pacific spans more than 100 million square kilometers and that planners must operate across "vast distances, with limited infrastructure and hostile domains." It also noted transit from the U.S. West Coast to Guam or Japan can exceed 6,000 miles.

Why it matters for Helios:

- Resilience cannot be measured only at the vendor level.
- The same supplier can be acceptable in a CONUS workflow and brittle in a Pacific mission thread if repair, refuel, or replacement cycles are too long.

### 2. Dispersed basing turns fuel, sustainment kits, and local site support into mission-critical dependencies

Source-backed fact:

- PACAF Strategy 2030 says PACAF must generate and sustain airpower from distributed locations in contested and degraded environments, and that it is increasing prepositioned materiel while diversifying resilient forward basing.
- Andersen AFB reported on May 7, 2025 that Project Carabao validated wet-wing defueling, forward refueling point establishment on Guam and Saipan, and secure communications over commercial Wi‑Fi for expeditionary sustainment operations.

Why it matters for Helios:

- Fuel and sustainment vendors that look "supporting" in a static dossier can become mission-critical in a First Island Chain ACE concept.
- Commercial network backhaul and expeditionary C2 kits are sustainment dependencies, not just IT details.

### 3. Conventional port assumptions are unsafe

Source-backed fact:

- The Army article on January 29, 2026 said planners must anticipate loss or degradation of conventional port infrastructure and pointed to joint logistics over-the-shore and redundant supply routes as critical.
- U.S. Pacific Fleet reported from Talisman Sabre 23 that joint petroleum over-the-shore operations were being validated as a critical Indo-Pacific logistics capability and specifically highlighted sustaining forces where permanent fuel infrastructure is absent.

Why it matters for Helios:

- Helios needs scenario coverage for offshore-to-shore distribution, commercial lighterage, fuel-transfer systems, and finance routes that keep those services alive.
- A vendor graph without maritime intermediaries and offload equipment is too shallow for this theater.

### 4. Alliances and agreements are not diplomatic garnish. They are logistics enablers

Source-backed fact:

- PACAF Strategy 2030 states that defense cooperation agreements, reciprocal access agreements, reciprocal aerial refueling certifications, and reciprocal maintenance agreements are essential to Indo-Pacific interoperability.
- The same strategy says allies and partners fill critical PACAF gaps.

Why it matters for Helios:

- Mission threads should explicitly model alternate maintenance, refueling, and support paths made possible by partner agreements.
- A substitute that exists in theory but is agreement-dependent or low-capacity should not be scored like a full alternate.

### 5. Forward repair depth is one of the highest-leverage resilience problems

Source-backed fact:

- On July 18, 2024, DoD announced a regional sustainment framework in the Indo-Pacific to create maintenance, repair, and overhaul capability close to where it is needed.
- DoD explicitly said this is meant to avoid shipping equipment from places like the Philippines back to the United States for repair.

Why it matters for Helios:

- Repair-node mapping is not a side feature. It is central to contested sustainment in this theater.
- Helios should treat repair certification, repair-site support, substitute maintenance, and repair-data services as first-class graph inputs.

### 6. Sustainment command and control is part of the logistics fight

Source-backed fact:

- Adm. Samuel Paparo said on May 13, 2025 that "in this AOR effective sustainment isn't just important, it's existential."
- The same Army article says the first battle in a conflict will be for information superiority in space and cyber.
- Project Carabao demonstrated sustainment communications over degraded links using commercial infrastructure as an operational workaround.

Why it matters for Helios:

- Intermediary edges like `depends_on_network` and `depends_on_service` belong inside contested logistics threads.
- A supply chain can be physically intact and still fail if sustainment routing, reporting, or release data cannot move.

### 7. Theater logistics posture is still being built out

Source-backed fact:

- The FY 2025 Pacific Deterrence Initiative says current theater logistics posture and capability are inadequate for contested operations and calls for a posture west of the International Date Line built around tactical and commercial distribution networks, prepositioning, maintenance, fuel, and munitions.

Why it matters for Helios:

- Helios should assume missing redundancy, not full redundancy.
- Test scenarios should reward explicit substitutes and punish implied resilience.

## Three Helios scenarios

### Scenario 1

Name: `first_island_chain_ace_refuel_c2`

Problem:

- Distributed air operations across Guam and Saipan depend on one primary refuel vendor, one expeditionary C2 maintainer, and one commercial backhaul path.

What this tests in Helios:

- `supports_site`
- `single_point_of_failure_for`
- `substitutable_with`
- `maintains_system_for`
- `depends_on_network`

Why it is Indo-Pacific-specific:

- It reflects ACE-style distributed operations, wet-wing defueling, austere site sustainment, and degraded communications across island chains.

### Scenario 2

Name: `littoral_jpots_fuel_offload_mesh`

Problem:

- A conventional port is unavailable, forcing fuel sustainment through offshore lighterage, expeditionary transfer gear, and a commercial settlement route.

What this tests in Helios:

- `distributed_by`
- `ships_via`
- `operates_facility`
- `routes_payment_through`
- `single_point_of_failure_for`

Why it is Indo-Pacific-specific:

- It reflects the region's dependence on maritime movement, austere shore reception, and the need to keep fuel flowing even when fixed infrastructure is denied.

### Scenario 3

Name: `regional_mro_reciprocal_maintenance_gap`

Problem:

- A mission-critical radar module has one primary repair source, a partial allied alternate, and a service dependency for release data.

What this tests in Helios:

- `maintains_system_for`
- `single_point_of_failure_for`
- `substitutable_with`
- `supports_site`
- `operates_facility`
- `depends_on_service`

Why it is Indo-Pacific-specific:

- It reflects the real value of regional sustainment centers and reciprocal maintenance agreements in avoiding CONUS repair timelines.

## Assumptions and gaps

- These scenarios are unclassified test abstractions, not campaign plans.
- The public sources are strong on operating problems and capability direction, but they do not expose operational plans, real supplier rosters, or real-time theater logistics data.
- The scenarios therefore encode the right failure modes rather than claiming to mirror a specific classified plan.

## Risks or watchouts

- Overfitting everything to a Taiwan-only fight would be sloppy. The AOR problem is broader than one contingency.
- Treating route optimization as the first Helios deliverable would be a mistake. Helios is currently stronger at resilience intelligence than movement execution.
- Assuming partner access is binary is also wrong. Agreement-dependent substitutes should remain lower-confidence than primary repair or support paths.

## Recommendation

Use the three scenario fixtures above as the standing regression pack for the contested logistics lane.

That gives Helios a disciplined first benchmark across:

- dispersed fuel generation
- degraded logistics C2
- austere shore offload
- maritime and finance intermediaries
- regional repair and reciprocal maintenance

## Next actions

- Seed the new INDOPACOM fixture pack locally and generate mission-thread briefings from all three scenarios.
- Use those briefings to refine mission-conditioned importance and resilience scoring before adding more UI polish.
- Keep future scenario additions aligned to official Indo-Pacific logistics problems, not generic supply-chain rhetoric.

## Sources

- U.S. Army, "AI-Driven Sustainment in Contested Logistics — Preparing for LSCO in the Indo-Pacific," January 29, 2026: [army.mil](https://www.army.mil/article-amp/290024/ai_driven_sustainment_in_contested_logistics_preparing_for_lsco_in_the_indo_pacific)
- U.S. Army, "INDOPACOM Commander Underscores Importance of Land Forces, Deterrence, and AI in Indo-Pacific Security," May 13, 2025: [army.mil](https://www.army.mil/article/285494/indopacom_commander_underscores_importance_of_land_forces_deterrence_and_ai_in_indo_pacific_security)
- PACAF Strategy 2030: [af.mil PDF](https://www.af.mil/Portals/1/documents/2023SAF/PACAF_Strategy_2030.pdf)
- Andersen AFB, "Project Carabao Enhances Agile Logistics Capabilities in the Indo-Pacific," May 7, 2025: [andersen.af.mil](https://www.andersen.af.mil/News/Articles/Article/4178121/project-carabao-enhances-agile-logistics-capabilities-in-the-indo-pacific/)
- DoD, "DOD Developing Regional Sustainment Framework in Indo-Pacific," July 18, 2024: [war.gov](https://www.war.gov/News/News-Stories/Article/Article/3843200/dod-developing-regional-sustainment-framework-in-indo-pacific/)
- U.S. Pacific Fleet, "U.S. Forces Validate Ship-to-Shore Logistics Capability at Talisman Sabre 23," July 28, 2023: [cpf.navy.mil](https://www.cpf.navy.mil/Newsroom/News/Article/3472052/us-forces-validate-ship-to-shore-logistics-capability-at-talisman-sabre-23/)
- FY 2025 Pacific Deterrence Initiative: [comptroller.defense.gov PDF](https://comptroller.defense.gov/Portals/45/Documents/defbudget/FY2025/FY2025_Pacific_Deterrence_Initiative.pdf)
