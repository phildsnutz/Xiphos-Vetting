# Graph Gap Fill Research

Generated: 2026-03-31

## Question

How should Helios fill the real gaps in its knowledge graph when the public information exists but the vendor-scoped graph is still thin?

## Bottom line

Helios does **not** mainly have a graph-model shortage.

It has a **source economics and orchestration shortage**:

1. The best ownership and control data is concentrated in a small set of official and quasi-official sources.
2. The best intermediary evidence lives in first-party websites, public DNS and registration metadata, and a narrow set of public procurement and filing documents.
3. Helios already has some of the right connectors, but several are either latent, under-seeded, or aimed at one-off lookups instead of bulk delta ingestion.

The highest-ROI move is **not** “more generic entity discovery.”

It is:

1. strengthen the identifier backbone
2. turn official ownership datasets into persistent feeds
3. mine first-party service, payment, and network dependencies from web and DNS surfaces
4. stop partial reruns from collapsing prior control paths

## Current truth from the live audit

From [graph-vendor-coverage-audit-20260331132006.md](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/docs/reports/graph_vendor_coverage_audit/graph-vendor-coverage-audit-20260331132006.md):

- global KG: `8,278` entities, `21,111` relationships, `2,395` vendor IDs
- `81.3%` of vendors map to exactly `1` entity
- `35.8%` have `0` root-relationship proxy coverage
- `71.9%` have `0` control-path proxy edges
- live relationship mix is rich in `subcontractor_of`, `filed_with`, `contracts_with`, and `prime_contractor_of`
- live relationship mix is still thin in `owned_by`, `backed_by`, and `beneficially_owned_by`

That means the graph is globally real but locally weak on the exact families that matter for hidden control and intermediary risk.

## What public information really exists

### 1. Official ownership and control backbones

#### GLEIF Level 2

What exists:

- GLEIF exposes direct and ultimate parent relationships through public API and bulk files.
- GLEIF also publishes mapping files between LEIs and OpenCorporates identifiers.

Why it matters:

- this is the cleanest global direct-parent and ultimate-parent backbone Helios can get without scraping random websites
- it is especially valuable for large enterprises, regulated suppliers, finance, and cross-border control paths

What Helios should do:

- treat LEI as a first-class graph key, not a nice-to-have identifier
- add bulk and delta ingest instead of only search-time lookups
- use LEI to bridge into SEC, OpenCorporates, and registry-specific connectors

Sources:

- [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api)
- [GLEIF Level 2 relationship data](https://www.gleif.org/en/lei-data/gleif-level-2-data-who-owns-whom)
- [GLEIF concatenated downloads](https://www.gleif.org/lei-data/gleif-concatenated-file/lei-download)
- [GLEIF OpenCorporates mapping files](https://www.gleif.org/en/lei-data/lei-mapping/download-oc-to-lei-relationship-files)

#### Open Ownership and BODS

What exists:

- Open Ownership publishes public beneficial-ownership data in the [Beneficial Ownership Data Standard](https://standard.openownership.org/en/0.4.0/).
- The public register already aggregates multiple national sources and mapped GLEIF data.

Why it matters:

- BODS is already the right statement model for “ownership or control” as claims, not just flat edges
- Helios already has a BODS-style import path, so this is a plumbing and activation problem, not a schema problem

What Helios should do:

- stop treating BODS as mainly a fixture lane
- ingest the public BODS data as a locally cached dataset with daily deltas
- normalize direct vs indirect statements into `owned_by` and `beneficially_owned_by`
- preserve statement IDs and interest metadata as first-class claim fields

Important repo-grounded note:

- [openownership_bods_public.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/openownership_bods_public.py) is structurally latent right now because it requires an `openownership_bods_url`, `bods_url`, or `XIPHOS_OPENOWNERSHIP_BODS_URL` to be configured

Sources:

- [Open Ownership Register](https://www.openownership.org/en/topics/open-ownership-register/)
- [BODS standard](https://standard.openownership.org/en/0.4.0/)
- [BODS data sources](https://bods-data.openownership.org/)

#### Country registries with PSC or beneficial ownership depth

What exists:

- UK Companies House exposes company profile, officers, PSC records, PSC statements, filing history, and a streaming API.
- Helios already has connectors for UK, Singapore, Norway, Netherlands, New Zealand, Australia, Canada, and France.

Why it matters:

- for many non-US suppliers, this is where the real control data lives
- PSC statements and filing history are often better than name-only search because they carry change events and structured authority

What Helios should do:

- prioritize stream or bulk-delta ingest over one-off per-vendor search
- keep statement IDs, ceased dates, and filing-event timestamps in claims
- route registry deltas into vendor refresh queues instead of waiting for manual case opens

Sources:

- [Companies House Public Data API](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/companyprofile?v=latest)
- [Companies House PSC list](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/persons-with-significant-control/list?v=latest)
- [Companies House PSC statements](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/persons-with-significant-control-statements/list?v=latest)
- [Companies House filing history](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/filinghistory/list?v=latest)
- [Companies House streaming API](https://developer-specs.company-information.service.gov.uk/streams/docs/)

### 2. US ownership is structurally harder than foreign ownership

This matters because Helios has a lot of US vendors.

What exists:

- FinCEN BOI is **not** a general public data source.
- SEC EDGAR is the best public US corporate-control source for public issuers.
- SAM and procurement systems can add identity, hierarchy hints, and contract topology.

Why it matters:

- Helios should stop expecting a universal public US beneficial ownership registry to save it
- for US private companies, the best practical path is a combination of first-party website evidence, procurement data, public filings, litigation, sanctions, and occasional registry bridges

What Helios should do:

- use SEC aggressively for listed or bond-issuing entities
- use SAM, FPDS, and USAspending for recipient and subaward structure
- rely more on first-party site, legal docs, and contract artifacts for private-company control and intermediary paths

Sources:

- [FinCEN BOI access and safeguards](https://fincen.gov/sites/default/files/shared/BOI_Access_and_Safeguards_SECG_508C.pdf)
- [FinCEN BOI rule changes and scope](https://www.fincen.gov/boi)
- [SEC developer resources](https://www.sec.gov/about/developer-resources)

### 3. SEC filings are underused for control and intermediary extraction

What exists:

- SEC EDGAR APIs, RSS feeds, and bulk index files
- Exhibit 21 subsidiary lists
- 8-Ks and Exhibit 10 credit agreements that often name lenders, guarantors, agents, and facilities

Why it matters:

- Helios already parses Exhibit 21 in [sec_edgar.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/sec_edgar.py)
- Helios does **not** yet appear to mine lender and facility relationships from Exhibit 10 or credit-agreement filings
- this is one of the cleanest public routes to `backed_by`, `routes_payment_through`, and control-adjacent bank exposure for public companies

What Helios should do:

- extend `sec_edgar` beyond `EX-21` to:
  - `EX-10` credit agreements
  - 8-K material financing disclosures
  - guarantee and security-interest language
- add a filing-event connector that turns SEC RSS and daily index files into graph refresh triggers

Sources:

- [SEC developer resources](https://www.sec.gov/about/developer-resources)
- [EDGAR APIs overview](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [EDGAR filings and feed access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC exhibit modernization rule discussing Exhibit 21](https://www.sec.gov/rules/final/2019/33-10618.pdf)

### 4. Contract topology is richer than Helios is currently using

What exists:

- USAspending exposes award and subaward APIs
- FPDS is already accessible through USAspending
- SAM public entity data and extracts add registration backbone

Why it matters:

- the graph already has many `subcontractor_of` and `prime_contractor_of` edges, but these are not consistently being turned into richer control-path context
- recipient-parent and subaward networks can help infer hidden concentration, dominant customer dependence, and common intermediaries

What Helios should do:

- use USAspending and FPDS not just for awards, but for:
  - repeated same-agency clustering
  - subaward ladders
  - parent recipient or related-entity normalization
- fuse contract topology with ownership and website dependency signals instead of treating them as separate silos

Sources:

- [USAspending API docs](https://api.usaspending.gov/docs/endpoints)
- [USAspending API overview](https://www.usaspending.gov/)
- [Open GSA data resources](https://open.gsa.gov/api/)

### 5. First-party websites are the missing intermediary graph

This is the biggest creative gap.

The ownership graph is hard partly because many vendors never disclose parents directly. But they **do** disclose the services and intermediaries they depend on:

- payment processors
- banks
- merchant providers
- cloud and hosting providers
- identity providers
- telecom and email providers
- DNS/CDN vendors
- support and status vendors

What exists publicly:

- HTML, JSON-LD, embedded JSON, sitemap, RSS, legal pages, privacy pages, terms pages, status pages
- JavaScript SDK and checkout signatures
- DNS and domain-registration metadata
- email and policy records

Why it matters:

- intermediary dependencies are often easier to find than direct ownership
- even when they do not prove control, they create high-signal service and payment subgraphs that make vendor neighborhoods stop being single-node islands

What Helios should do:

#### Structured data extraction

Parse first-party structured data for:

- `Organization`
- `legalName`
- `leiCode`
- `sameAs`
- `parentOrganization`
- `subOrganization`
- `acceptedPaymentMethod`

Sources:

- [schema.org Organization](https://schema.org/Organization)
- [schema.org parentOrganization](https://schema.org/parentOrganization)
- [schema.org acceptedPaymentMethod](https://schema.org/acceptedPaymentMethod)

#### Deterministic technology fingerprints

Add deterministic signatures for:

- Stripe
- PayPal
- Braintree
- Adyen
- Shopify
- Cloudflare
- Microsoft 365
- Google Workspace
- Okta
- Atlassian Statuspage
- Zendesk
- Salesforce

These are often visible through:

- script URLs
- iframe and checkout endpoints
- JS globals
- response headers
- status domains
- SPF and DMARC includes
- MX records

Sources:

- [Stripe.js docs](https://docs.stripe.com/js)
- [PayPal JavaScript SDK](https://developer.paypal.com/sdk/js/)
- [RFC 7208 SPF](https://datatracker.ietf.org/doc/html/rfc7208)
- [RFC 7489 DMARC](https://datatracker.ietf.org/doc/html/rfc7489)

#### Domain and network registration evidence

Use public registration and routing evidence for:

- RDAP organization and contact data
- nameserver and registrar clustering
- ASN and network-operator fingerprints
- certificate transparency subdomains

Why it matters:

- this is the cleanest public way to build `depends_on_network` and `depends_on_service` edges when websites are thin
- it also helps canonicalize first-party hosts and distinguish vendor infrastructure from third-party SaaS

Sources:

- [RFC 7484 RDAP bootstrap](https://datatracker.ietf.org/doc/html/rfc7484)
- [IANA RDAP bootstrap service](https://data.iana.org/rdap/)
- [PeeringDB API docs](https://docs.peeringdb.com/api_specs/)
- [Certificate Transparency](https://certificate.transparency.dev/)

### 6. Analysts should be allowed to import high-signal artifacts

The user’s prompt says the information is out there. That is true. But some of the most valuable proof lives in analyst-visible artifacts that are not publicly indexed:

- ACH or remittance instructions
- W-9 or vendor setup forms
- invoice PDFs
- supplier portal screenshots
- capability statements
- onboarding packets

These should **not** replace public connectors.

They should sit beside them as claim-evidence imports, because they are often the fastest route to:

- `routes_payment_through`
- `depends_on_service`
- `backed_by`
- `officer_of`
- `beneficially_owned_by`

This is still compatible with the current local-first collector lab posture because the import contract is already provider-neutral.

## What Helios is underusing today

### 1. Existing connectors that are not fully activated

- [openownership_bods_public.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/openownership_bods_public.py) needs configured dataset location, so it is effectively dormant unless seeded
- [sec_edgar.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/sec_edgar.py) already parses Exhibit 21, but not the richer financing and lender surfaces from Exhibit 10 or financing-related 8-Ks
- [sec_xbrl.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/sec_xbrl.py) is currently financial-ratio oriented, not control-path oriented
- [public_html_ownership.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/public_html_ownership.py) is now better on payment and service hints, but it still needs structured JSON-LD, DNS, email-policy, and vendor-technology fingerprints
- [public_search_ownership.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/public_search_ownership.py) is good for discovery, but should become a trigger and site-seeding layer, not the main truth layer

### 2. The current orchestration is search-first when it should be backbone-first

Best practice for vendor graph growth:

1. canonicalize vendor identity
2. enrich identifiers
3. hit official backbone registries
4. only then fan out to website and discovery connectors
5. use media and search as supporting evidence, not core control truth

Helios is directionally there, but the thinness audit says it still is not happening reliably at scale.

### 3. Bulk delta sources are better than endless per-vendor search

The best next wave of graph thickening should come from:

- daily or periodic GLEIF refresh
- cached BODS dataset refresh
- Companies House and filing streams
- SEC index and RSS deltas
- recurring coverage audit against the vendor population

This is better than hoping each open case happens to rediscover the same entity.

## Best next implementation order

### Tranche 1: Make the current graph stop missing obvious public intermediary edges

Target files:

- [public_html_ownership.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/public_html_ownership.py)
- [public_search_ownership.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/public_search_ownership.py)
- [fdic_bankfind.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/fdic_bankfind.py)
- [graph_ingest.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/graph_ingest.py)

Build:

- JSON-LD parser for `Organization`, `parentOrganization`, `acceptedPaymentMethod`, `leiCode`, `sameAs`
- deterministic Stripe, PayPal, Cloudflare, M365, Google Workspace, Okta, Zendesk, Statuspage signatures
- DNS and email-policy mini-connector for RDAP, MX, SPF, DMARC
- normalize extracted bank names through FDIC when the target is US-regulated

Why first:

- fastest path to reducing single-node vendor graphs
- no anti-bot games required
- highly replayable with fixtures

### Tranche 2: Turn official ownership into a real persistent feed

Target files:

- [openownership_bods_public.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/openownership_bods_public.py)
- [gleif_lei.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/gleif_lei.py)
- [uk_companies_house.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/uk_companies_house.py)
- new cached bulk-loader scripts under [scripts/](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/scripts)

Build:

- local BODS dataset cache with daily refresh and fast local lookups
- GLEIF bulk refresh for LEI and parent chains
- Companies House PSC and filing stream replays into fixtures first
- persistent identifier bridging from website and resolver output into registry connectors

Why second:

- biggest step change for `owned_by` and `beneficially_owned_by`
- moves Helios from one-off lookup to cumulative ownership memory

### Tranche 3: Expand SEC from “public-company context” to “control and financing extractor”

Target files:

- [sec_edgar.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/sec_edgar.py)
- [sec_xbrl.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/backend/osint/sec_xbrl.py)

Build:

- parse `EX-10` credit agreements
- extract lender, administrative agent, guarantor, revolver, factoring, and security-interest entities
- use SEC filing deltas as refresh triggers for graph claims

Why third:

- best public route to financing and payment-route edges for listed firms
- complements GLEIF instead of duplicating it

### Tranche 4: Make thinness a tracked KPI

Target files:

- [run_graph_vendor_coverage_audit.py](/Users/tyegonzalez/Desktop/Helios-Package%20Merged/scripts/run_graph_vendor_coverage_audit.py)
- recurring hardening report scripts

Track:

- `% vendors with 0 control-path edges`
- `% vendors with only 1 mapped entity`
- average ownership or intermediary edges per vendor
- coverage by lane and by country
- connector yield by family

## What not to waste time on first

- generic media-only ownership extraction as the main engine
- black-box relation extraction without claim provenance
- massive state-registry sprawl before exploiting GLEIF, BODS, SEC, and first-party web evidence
- building more synthetic graph volume that does not improve vendor-scoped control paths

## Recommendation

The best way to fill Helios graph gaps is:

1. **activate** the official ownership backbone that already exists
2. **mine first-party websites and DNS surfaces** for service, payment, and network intermediaries
3. **upgrade SEC extraction** from subsidiary lists to financing and lender structure
4. **treat thinness as a measured KPI**, not a vague feeling

If Helios does that, the graph stops being “a lot of companies with a few edges” and becomes “a vendor memory system that retains ownership, dependency, and payment structure even when no single source tells the whole truth.”

## Sources

- [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api)
- [GLEIF Level 2 data](https://www.gleif.org/en/lei-data/gleif-level-2-data-who-owns-whom)
- [GLEIF concatenated downloads](https://www.gleif.org/lei-data/gleif-concatenated-file/lei-download)
- [GLEIF OpenCorporates mapping](https://www.gleif.org/en/lei-data/lei-mapping/download-oc-to-lei-relationship-files)
- [Open Ownership Register](https://www.openownership.org/en/topics/open-ownership-register/)
- [BODS standard](https://standard.openownership.org/en/0.4.0/)
- [BODS data sources](https://bods-data.openownership.org/)
- [Companies House company profile API](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/companyprofile?v=latest)
- [Companies House PSC API](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/persons-with-significant-control/list?v=latest)
- [Companies House PSC statements API](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/persons-with-significant-control-statements/list?v=latest)
- [Companies House filing history API](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/filinghistory/list?v=latest)
- [Companies House streaming API](https://developer-specs.company-information.service.gov.uk/streams/docs/)
- [FinCEN BOI access and safeguards](https://fincen.gov/sites/default/files/shared/BOI_Access_and_Safeguards_SECG_508C.pdf)
- [FinCEN BOI program](https://www.fincen.gov/boi)
- [SEC developer resources](https://www.sec.gov/about/developer-resources)
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [Accessing EDGAR data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [SEC Exhibit 21 modernization rule](https://www.sec.gov/rules/final/2019/33-10618.pdf)
- [USAspending API docs](https://api.usaspending.gov/docs/endpoints)
- [Open GSA APIs](https://open.gsa.gov/api/)
- [schema.org Organization](https://schema.org/Organization)
- [schema.org parentOrganization](https://schema.org/parentOrganization)
- [schema.org acceptedPaymentMethod](https://schema.org/acceptedPaymentMethod)
- [Stripe.js docs](https://docs.stripe.com/js)
- [PayPal JavaScript SDK](https://developer.paypal.com/sdk/js/)
- [RFC 7208 SPF](https://datatracker.ietf.org/doc/html/rfc7208)
- [RFC 7489 DMARC](https://datatracker.ietf.org/doc/html/rfc7489)
- [RFC 7484 RDAP bootstrap](https://datatracker.ietf.org/doc/html/rfc7484)
- [IANA RDAP bootstrap data](https://data.iana.org/rdap/)
- [PeeringDB API docs](https://docs.peeringdb.com/api_specs/)
- [Certificate Transparency](https://certificate.transparency.dev/)
