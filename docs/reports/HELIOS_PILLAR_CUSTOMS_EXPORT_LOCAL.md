# Helios AI-In-The-Loop Export Gauntlet

- Fixture: `pillar_customs_export_trade_evasion_cases.json`
- Scenarios: `3`
- Passed: `3`
- Failed: `0`
- Pass rate: `100.0%`
- Deterministic baseline accuracy: `0.0%`
- Hybrid posture accuracy: `100.0%`
- Disagreement accuracy: `100.0%`
- Overall score: `98.1%`
- Hybrid outperformed deterministic on: `3` scenarios
- Hybrid avoided regressions on: `3` scenarios

## Hybrid Posture Distribution

- `escalate`: `3`

## Scenario Results

### Third-country transshipment to hide end user or origin

- Status: `PASS`
- Score: `100.0%`
- Deterministic posture: `likely_nlr`
- Expected deterministic posture: `likely_nlr`
- AI proposed posture: `escalate`
- Hybrid posture: `escalate`
- Expected hybrid posture: `escalate`
- AI disagreement expected / actual: `True` / `True`
- Ambiguity flags: `transshipment_or_intermediary, integration_ambiguity`
- Missing facts: `final_end_use, operational_scope, final_end_user, final_country, intermediary_role`
- AI explanation: Ambiguous end-use narrative detected with transshipment or intermediary, integration ambiguity. Helios should verify final_end_use, operational_scope, final_end_user, final_country before clearance.

### Deemed export inside U.S. operations

- Status: `PASS`
- Score: `94.3%`
- Deterministic posture: `likely_exception_or_exemption`
- Expected deterministic posture: `likely_license_required`
- AI proposed posture: `escalate`
- Hybrid posture: `escalate`
- Expected hybrid posture: `escalate`
- AI disagreement expected / actual: `True` / `True`
- Ambiguity flags: `remote_access_to_technical_data, foreign_person_access, agreement_scope_or_proviso_gap`
- Missing facts: `remote_access_scope, ttcp_or_tcp, taa_mla_wda_reference, proviso_scope, proviso_acceptance`
- AI explanation: Ambiguous end-use narrative detected with remote access to technical data, foreign person access, agreement scope or proviso gap. Helios should verify remote_access_scope, ttcp_or_tcp, taa_mla_wda_reference, proviso_scope before clearance.
- Missing-fact gaps: `authorized_person_list; access_location`

### Dual-use component in a sensitive end use

- Status: `PASS`
- Score: `100.0%`
- Deterministic posture: `likely_nlr`
- Expected deterministic posture: `likely_nlr`
- AI proposed posture: `escalate`
- Hybrid posture: `escalate`
- Expected hybrid posture: `escalate`
- AI disagreement expected / actual: `True` / `True`
- Ambiguity flags: `special_project, integration_ambiguity`
- Missing facts: `final_end_use, operational_scope, program_name, sponsoring_customer`
- AI explanation: Ambiguous end-use narrative detected with special project, integration ambiguity. Helios should verify final_end_use, operational_scope, program_name, sponsoring_customer before clearance.

## Readout

- The AI challenge layer is improving posture quality on ambiguous narratives without downgrading hard deterministic postures.
- Helios is strongest when the deterministic floor owns hard stops and the AI layer owns ambiguity, missing facts, and disciplined escalation.
