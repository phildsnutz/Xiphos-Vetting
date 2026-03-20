# Xiphos v5.2.2 Project State

## What Is Xiphos
Multi-vertical compliance and vendor vetting platform serving BOTH commercial AND Department of Defense (DoD) supply chains. Screens vendors through 27 live OSINT connectors, a 14-factor FGAMLogit probabilistic scoring engine, and a 10-gate regulatory compliance engine.

## Architecture: Two-Layer Scoring
- **Layer 1: Regulatory Gate Engine** (regulatory_gates.py) - 10 deterministic DoD compliance gates: Section 889, ITAR, EAR, DFARS Specialty Metals, CDI, CMMC 2.0, FOCI, NDAA 1260H, CFIUS, Berry Amendment
- **Layer 2: FGAMLogit Probabilistic Scorer** (fgamlogit.py) - 14-factor sensitivity-aware logistic model with tier weight multipliers and DoD factor priors
- **Layer Integration**: Maps (regulatory_status x risk_probability x sensitivity) to combined tier + program recommendation
- **Single scoring path**: ONE call to score_vendor() in server.py, inside _score_and_persist(). Every endpoint flows through it.

## Sensitivity Tiers (Xiphos-native, NOT classification markings)
CRITICAL_SAP, CRITICAL_SCI, ELEVATED, ENHANCED, CONTROLLED, STANDARD, COMMERCIAL
Color coded: RED, RED, ORANGE, YELLOW, BLUE, GREEN, gray

## Key Design Decisions
- Uniform baseline (-2.94 = 5% for perfect vendor) across all sensitivity tiers
- Sensitivity differentiation comes entirely from factor WEIGHTS, not baseline
- Supply chain tier multiplier: T0=0.70x, T1=1.00x, T2=1.30x, T3=1.60x (on uncertainty factors only)
- DoD factor priors for unknowns: small tier-based values, not 0.0
- Allied-nation false-positive mitigation on sanctions hard stops
- PROGRAM_TO_SENSITIVITY map is single source of truth in fgamlogit.py
- Hard stops are CATEGORICAL (p=1.0, TIER_1_DISQUALIFIED), not probability floors
- Extra risk signals from OSINT map to actual scoring fields (not phantom dicts)
- Inferred data labeled [INFERRED] with reduced confidence (0.60)

## Infrastructure
- Reference deployment: containerized Flask/Gunicorn on `:8080` behind an HTTPS reverse proxy
- Runtime state: provided via `XIPHOS_DATA_DIR` (SQLite DBs, sanctions cache, knowledge graph)
- Docker: `docker compose build --no-cache && docker compose up -d`
- Current tag: v5.2.2
- Public URLs, SSH details, and secrets are intentionally environment-specific and should live in deployment configuration, not this document.

## Key Files
- **fgamlogit.py**: Canonical v5.0 scorer. 14 factors, sensitivity-aware weights, tier multipliers, DoD priors, layer integration, hard stops, soft flags, MIV, Wilson CI
- **regulatory_gates.py**: 10-gate deterministic Layer 1. Section 889, ITAR, EAR, DFARS, CDI, CMMC, FOCI, NDAA 1260H, CFIUS, Berry
- **server.py**: Flask API. Single scoring path via _score_and_persist(). Runs Layer 1 gates for DoD cases automatically.
- **osint_scoring.py**: Translates OSINT enrichment findings into scoring inputs. 8 extraction blocks for years_of_records, known_execs, adverse_media, pep, litigation, state_owned, foreign_ownership, DUNS
- **monitor_scheduler.py**: Continuous monitoring with Layer 1 gates
- **profiles.py**: 5 compliance profiles (defense, ITAR, research, grants, commercial). Connector orchestration only (scoring weights in fgamlogit.py)
- **ofac.py**: v3.0 5-signal composite sanctions matching (IDF tokens, Dice bigram, JW, phonetic, length ratio)
- **tokens.ts**: Frontend tier system. 13 TierKey values + UNSCORED, TierBand aggregation, SensitivityKey with color metadata
- **types.ts**: Calibration interface with v5.0 DoD fields including interval_coverage

## Historical MQ-9 Analysis Benchmark (v5.1.1)
Historical benchmark run: 22 vendors, ELEVATED sensitivity, 27 OSINT connectors per vendor
Spread: 68.8pp (11.7% to 80.5%)
- TIER_4_APPROVED (7): GA-ASI 11.7%, L3Harris 16.3%, Collins 16.3%, Raytheon 18.5%, Lockheed 18.5%, Northrop 18.5%, Leonardo DRS 22.8%
- TIER_3_CONDITIONAL (11): Parker 26.4%, Curtiss-Wright 26.4%, Sierra Nevada 26.4%, BAE 26.7%, Ultra 32.1%, Woodward 34.5%, Honeywell 35.4%, Elbit 37.2%, Cobham 37.2%, Kaman 37.2%, Korea Aerospace 39.3%
- TIER_2_ELEVATED (4): Moog 41.0%, Safran 61.0%, TAI 77.6%, Thales 80.5%

## Audit Status
- Core backend, frontend, dossier, async AI, intel summary, and event normalization paths have been hardened through the latest audit pass.
- Remaining high-priority operational follow-up is credential rotation/history scrubbing outside this repo.
- Environment-specific deployment values should be supplied via deployment configuration, not committed documentation.
