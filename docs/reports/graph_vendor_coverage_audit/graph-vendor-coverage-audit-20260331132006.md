# Helios Vendor Graph Coverage Audit

Generated: 2026-03-31T13:20:06Z
Database: `/Users/tyegonzalez/Desktop/Helios-Package Merged/var/knowledge_graph.live.snapshot.db`

## Verdict

- The live knowledge graph is not globally thin.
- The vendor-scoped control graph is thin.
- The gap is ownership, financing, bank-route, and intermediary coverage per vendor.

## Global Counts

- Entities: `8278`
- Relationships: `21111`
- Claims: `7171`
- Evidence records: `7171`
- Vendor links: `5941`
- Distinct vendor IDs: `2395`

## Vendor Coverage

- Average mapped entities per vendor: `2.4806`
- Vendors with exactly 1 mapped entity: `1948` (`81.3%`)
- Vendors with 0 root-entity relationships (proxy): `857` (`35.8%`)
- Vendors with 0 control-path edges (proxy): `1723` (`71.9%`)
- Vendors with any control-path edge (proxy): `672`

## Buckets

- Mapped entities per vendor: `{'1': 1948, '2': 151, '3-5': 141, '6-10': 55, '11+': 100}`
- Root relationships per vendor (proxy): `{'0': 857, '1': 146, '2': 58, '3-5': 254, '6-10': 229, '11+': 851}`
- Control-path relationships per vendor (proxy): `{'0': 1723, '1': 278, '2': 63, '3-5': 323, '6-10': 8}`

## Relationship Mix

- Top relationship types: `{'subcontractor_of': 6906, 'filed_with': 4846, 'contracts_with': 3435, 'prime_contractor_of': 2482, 'subsidiary_of': 1810, 'litigant_in': 1087, 'sanctioned_on': 207, 'mentioned_with': 180, 'owned_by': 58, 'backed_by': 23, 'alias_of': 17, 'screened_for': 15}`
- Entity types: `{'company': 7936, 'court_case': 181, 'holding_company': 91, 'government_agency': 35, 'person': 16, 'sanctions_list': 7, 'case': 6, 'country': 5, 'export_control': 1}`

## Diagnosis

- The live KG is globally large but vendor-scoped control graphs are thin.
- Most vendors map to one entity and never grow a meaningful ownership, financing, bank-route, or service-intermediary neighborhood.
- Relationship and control-path buckets are a root-entity proxy from vendor-linked source entities. The dossier path is stricter because it filters down to vendor-scoped claims, so real case-level thinness is usually worse than this report.
- The missing edge families are still ownership/control and intermediary evidence, not generic company discovery.

## Samples

- Dense vendor IDs: `['c-1655d7d0', 'c-7b6b05b3', 'c-06b5564a', 'c-2e43f6fc', 'c-7374e890', 'c-7df8ca69', 'c-03fc28d9', 'c-afeaf0e7', 'c-27a79174', 'c-0a78d7ed']`
- Zero-control vendor IDs: `['c-000bb34c', 'c-005a17a7', 'c-0061113e', 'c-006215e7', 'c-008b41d0', 'c-009edf16', 'c-00b8763f', 'c-00cf613c', 'c-012fa0b2', 'c-016ba119']`
