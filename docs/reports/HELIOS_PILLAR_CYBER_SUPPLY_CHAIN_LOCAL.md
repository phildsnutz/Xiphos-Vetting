# Helios Supply Chain Assurance Gauntlet

- Fixture: `pillar_cyber_supply_chain_assurance_cases.json`
- Scenarios: `3`
- Passed: `3`
- Failed: `0`
- Pass rate: `100.0%`
- Deterministic baseline accuracy: `33.3%`
- Hybrid posture accuracy: `100.0%`
- Disagreement accuracy: `100.0%`
- Overall score: `97.3%`
- Hybrid outperformed deterministic on: `2` scenarios
- Hybrid avoided regressions on: `3` scenarios

## Hybrid Posture Distribution

- `blocked`: `1`
- `review`: `2`

The AI challenge layer is improving assurance quality when the raw cyber score misses provenance gaps, fourth-party concentration, or artifact-backed false alarms.

## Scenario Results

### KEV-rich product in a sensitive environment

- Status: `PASS`
- Score: `100.0%`
- Deterministic tier / posture: `HIGH` / `review`
- Hybrid posture: `blocked`
- Expected hybrid posture: `blocked`
- AI disagreement expected / actual: `True` / `True`
- Ambiguity flags: `mission_critical_dependency, firmware_or_ot_exposure`
- Missing facts: `firmware_update_path`
- AI explanation: Supply chain assurance ambiguity detected across mission critical dependency, firmware or ot exposure. Helios should verify firmware update path before clearance.

### Secure-by-design marketing without artifact proof

- Status: `PASS`
- Score: `92.0%`
- Deterministic tier / posture: `LOW` / `qualified`
- Hybrid posture: `review`
- Expected hybrid posture: `review`
- AI disagreement expected / actual: `True` / `True`
- Ambiguity flags: `sbom_vex_gap, marketing_without_artifacts, mission_critical_dependency, provenance_gap`
- Missing facts: `fresh_sbom, vex_assertion, secure_by_design_artifacts, provenance_attestation`
- AI explanation: Supply chain assurance ambiguity detected across sbom vex gap, marketing without artifacts, mission critical dependency, provenance gap. Helios should verify fresh sbom, vex assertion, secure by design artifacts, provenance attestation before clearance.
- Missing expected flags: `cmmc_evidence_gap`
- Missing expected facts: `current_cmmc_evidence`

### Compromised update / signing / MSP path

- Status: `PASS`
- Score: `100.0%`
- Deterministic tier / posture: `MODERATE` / `review`
- Hybrid posture: `review`
- Expected hybrid posture: `review`
- AI disagreement expected / actual: `False` / `False`
- Ambiguity flags: `sbom_vex_gap, fourth_party_concentration, mission_critical_dependency, firmware_or_ot_exposure`
- Missing facts: `fresh_sbom, fourth_party_dependency_map, firmware_update_path`
- AI explanation: Supply chain assurance ambiguity detected across sbom vex gap, fourth party concentration, mission critical dependency, firmware or ot exposure. Helios should verify fresh sbom, fourth party dependency map, firmware update path before clearance.

## Readout

The current assurance lane is much better with an AI challenge layer above the deterministic cyber score. It can now call out provenance gaps, SBOM or VEX weakness, fourth-party concentration, and artifact-backed false positives without hiding the deterministic baseline.
