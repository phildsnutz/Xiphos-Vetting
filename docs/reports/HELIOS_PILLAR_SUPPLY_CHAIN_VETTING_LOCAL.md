# Helios Adversarial Gym Report

Fixture: `fixtures/adversarial_gym/pillar_supply_chain_vetting_assurance_cases.json`

## Summary

- Scenarios: `3`
- Passed: `3`
- Failed: `0`
- Pass rate: `1.0`

## Results

### Hidden foreign influence in a domestic defense supplier

- Expected view: `deny`
- Recommended view: `deny`
- Consensus: `contested`
- Decision gap: `0.01`
- Target score: `0.71`
- Status: `pass`

- `Deny / Block`: `0.71` via foreign_control_risk, compound_export_control, network_pressure, cyber_gap, compound_control_path
- `Watch / Conditional`: `0.7` via review_posture, analyst_escalate, export_review, cyber_gap, network_pressure, foreign_control_context, intermediary_paths
- `Approve / Proceed`: `0.15` via no_hard_stop, identifier_depth, coverage_depth, no_contradictions, fresh_control_paths

### Shell / nominee pass-through subcontractor

- Expected view: `watch`
- Recommended view: `watch`
- Consensus: `strong`
- Decision gap: `0.24`
- Target score: `0.66`
- Status: `pass`

- `Watch / Conditional`: `0.66` via review_posture, network_pressure, foreign_control_context, stale_claims, intermediary_paths
- `Approve / Proceed`: `0.42` via no_hard_stop, export_clear, cyber_clear, identifier_depth, coverage_depth, no_contradictions
- `Deny / Block`: `0.23` via foreign_control_risk, compound_control_path

### Lower-tier supplier with concealed dependency

- Expected view: `watch`
- Recommended view: `watch`
- Consensus: `strong`
- Decision gap: `0.26`
- Target score: `0.84`
- Status: `pass`

- `Watch / Conditional`: `0.84` via review_posture, network_pressure, thin_control_paths, contradictory_claims, stale_claims, intermediary_paths
- `Approve / Proceed`: `0.58` via no_hard_stop, export_clear, cyber_clear, identifier_depth, coverage_depth, ownership_clear
- `Deny / Block`: `0.09` via contradictory_claims
