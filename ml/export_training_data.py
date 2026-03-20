#!/usr/bin/env python3
"""
Xiphos Helios ML Training Data Exporter

Connects to the live Helios API, pulls all OSINT enrichment findings,
and exports them as a labeled CSV for DistilBERT fine-tuning.

Labels:
  1 = genuinely adverse (sanctions, fraud, indictment, debarment, etc.)
  0 = not adverse (partnership, award, neutral news, clearance, etc.)

The labeling uses a high-confidence heuristic based on:
  - Source reliability (government sources > media)
  - Finding category (exclusion/sanctions vs media/clearance)
  - Severity as assigned by the connector
  - Known false-positive patterns

Run: python3 ml/export_training_data.py
Output: ml/training_data.csv
"""

import requests
import warnings
import csv
import re
import sys
import os

warnings.filterwarnings('ignore')

BASE = os.environ.get("HELIOS_BASE_URL", "").strip()
EMAIL = os.environ.get("HELIOS_LOGIN_EMAIL", "").strip()
PASSWORD = os.environ.get("HELIOS_LOGIN_PASSWORD", "").strip()
VERIFY_TLS = os.environ.get("HELIOS_VERIFY_TLS", "false").lower() == "true"
OUTPUT = os.environ.get("HELIOS_TRAINING_EXPORT_PATH", "ml/training_data.csv")

# High-confidence adverse categories (from authoritative sources)
ADVERSE_CATEGORIES = {'exclusion', 'sanctions', 'adverse_media', 'litigation', 'pep'}

# High-confidence non-adverse categories
CLEAR_CATEGORIES = {'clearance', 'media', 'government_contracts', 'financial', 'identity'}

# Known false-positive headline patterns (things that LOOK adverse but aren't)
FALSE_POSITIVE_PATTERNS = [
    r'partner(s|ship|ed|ing)',
    r'award(s|ed)',
    r'contract\s+(award|win|won)',
    r'collaborat(e|ion|ing)',
    r'launch(es|ed|ing)',
    r'expand(s|ed|ing)',
    r'acquir(e|es|ed|ing)',  # Acquisitions are neutral
    r'invest(s|ed|ment|ing)',
    r'hire(s|d|ing)',
    r'promot(e|es|ed|ion)',
    r'certif(y|ied|ication)',
    r'approv(e|ed|al)',
    r'clear(s|ed|ance)',
    r'no\s+match',
    r'not\s+found',
    r'verified',
]

# Known true-positive adverse patterns
TRUE_ADVERSE_PATTERNS = [
    r'sanction(s|ed)',
    r'fraud',
    r'indict(ed|ment)',
    r'lawsuit',
    r'penalty|penalized',
    r'scandal',
    r'bankruptcy',
    r'subpoena',
    r'convicted',
    r'debarr(ed|ment)',
    r'money\s+launder',
    r'brib(e|ery)',
    r'corrupt(ion)?',
    r'embezzl(e|ement)',
    r'insider\s+trading',
    r'violation',
    r'exclusion',
    r'blocked\s+person',
    r'prohibited',
    r'terminated\s+for\s+(cause|default)',
    r'espionage',
    r'exploit',
]


def label_finding(finding: dict) -> int:
    """Assign a label to a finding: 1 = adverse, 0 = not adverse."""
    title = (finding.get('title', '') or '').lower()
    detail = (finding.get('detail', '') or '').lower()
    text = f"{title} {detail}"
    category = finding.get('category', '')
    severity = finding.get('severity', 'info')
    source = finding.get('source', '')

    # Rule 1: Government sanctions/exclusion sources are authoritative
    if category in ('exclusion', 'sanctions') and severity in ('critical', 'high'):
        return 1

    # Rule 2: Clearance findings are definitively non-adverse
    if category == 'clearance':
        return 0

    # Rule 3: Info severity is almost always non-adverse
    if severity == 'info' and category not in ADVERSE_CATEGORIES:
        return 0

    # Rule 4: Check for known false-positive patterns
    for pattern in FALSE_POSITIVE_PATTERNS:
        if re.search(pattern, text):
            return 0

    # Rule 5: Check for known true-adverse patterns
    for pattern in TRUE_ADVERSE_PATTERNS:
        if re.search(pattern, text):
            return 1

    # Rule 6: Media findings with medium+ severity from reliable sources
    if category == 'adverse_media' and severity in ('medium', 'high', 'critical'):
        return 1

    # Rule 7: PEP/litigation findings
    if category in ('pep', 'litigation') and severity != 'info':
        return 1

    # Default: non-adverse (conservative)
    return 0


def main():
    if not BASE or not EMAIL or not PASSWORD:
        print("Set HELIOS_BASE_URL, HELIOS_LOGIN_EMAIL, and HELIOS_LOGIN_PASSWORD before running this export.")
        sys.exit(2)

    # Login
    print("Connecting to Helios API...")
    login = requests.post(f'{BASE}/api/auth/login',
        json={'email': EMAIL, 'password': PASSWORD},
        verify=VERIFY_TLS, timeout=15)
    if login.status_code != 200:
        print(f"Login failed: {login.status_code}")
        sys.exit(1)

    token = login.json()['token']
    h = {'Authorization': f'Bearer {token}'}

    # Get all cases
    print("Fetching cases...")
    resp = requests.get(f'{BASE}/api/cases?limit=500', headers=h, verify=VERIFY_TLS, timeout=30)
    cases = resp.json().get('cases', [])
    print(f"Found {len(cases)} cases")

    # Export findings from each case's enrichment
    all_findings = []
    for i, case in enumerate(cases):
        cid = case['id']
        name = case.get('vendor_name', '')
        resp = requests.get(f'{BASE}/api/cases/{cid}/enrichment', headers=h, verify=VERIFY_TLS, timeout=30)
        if resp.status_code != 200:
            continue

        report = resp.json()
        findings = report.get('findings', [])
        for f in findings:
            title = f.get('title', '')
            detail = f.get('detail', '')
            if not title:
                continue

            label = label_finding(f)
            all_findings.append({
                'text': f"{title}. {detail[:200]}" if detail else title,
                'title': title,
                'detail': detail[:300] if detail else '',
                'source': f.get('source', ''),
                'category': f.get('category', ''),
                'severity': f.get('severity', 'info'),
                'confidence': f.get('confidence', 0),
                'vendor': name,
                'label': label,
            })

        if (i + 1) % 10 == 0:
            print(f"  Processed {i+1}/{len(cases)} cases ({len(all_findings)} findings)")

    # Also generate synthetic training examples for edge cases
    synthetic_adverse = [
        "Company X indicted on fraud charges related to defense contracts",
        "CEO of vendor convicted of bribery in federal procurement scheme",
        "Vendor sanctioned by OFAC for ties to designated entity",
        "Company debarred from federal contracting for false claims",
        "Subsidiary linked to money laundering investigation by DOJ",
        "Vendor's export license revoked due to ITAR violations",
        "Former executive charged with insider trading",
        "Company fined $50M for environmental violations at defense facility",
        "Vendor placed on Entity List for technology transfer to adversary nation",
        "CFIUS ordered divestiture due to national security concerns",
    ]

    synthetic_non_adverse = [
        "Company awarded $200M contract for next-generation radar systems",
        "Vendor partners with NATO ally on joint defense program",
        "Company achieves CMMC Level 2 certification ahead of schedule",
        "Vendor expands manufacturing facility creating 500 new jobs",
        "Company announces strategic investment in AI defense capabilities",
        "Vendor selected for SBIR Phase III technology transition",
        "Company reports strong quarterly earnings exceeding analyst estimates",
        "Vendor receives Department of Defense Nunn-Perry Award for mentor-protege excellence",
        "Company completes acquisition of cybersecurity subsidiary",
        "Vendor launches new satellite communications platform for allied forces",
    ]

    for text in synthetic_adverse:
        all_findings.append({
            'text': text, 'title': text, 'detail': '', 'source': 'synthetic',
            'category': 'adverse_media', 'severity': 'high', 'confidence': 1.0,
            'vendor': 'SYNTHETIC', 'label': 1,
        })

    for text in synthetic_non_adverse:
        all_findings.append({
            'text': text, 'title': text, 'detail': '', 'source': 'synthetic',
            'category': 'media', 'severity': 'info', 'confidence': 1.0,
            'vendor': 'SYNTHETIC', 'label': 0,
        })

    # Write CSV
    print(f"\nTotal findings: {len(all_findings)}")
    adverse_count = sum(1 for f in all_findings if f['label'] == 1)
    print(f"Adverse (label=1): {adverse_count} ({adverse_count/len(all_findings)*100:.1f}%)")
    print(f"Non-adverse (label=0): {len(all_findings) - adverse_count} ({(len(all_findings)-adverse_count)/len(all_findings)*100:.1f}%)")

    with open(OUTPUT, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            'text', 'label', 'title', 'detail', 'source', 'category',
            'severity', 'confidence', 'vendor',
        ])
        writer.writeheader()
        writer.writerows(all_findings)

    print(f"\nExported to {OUTPUT}")
    print("Next step: python3 ml/train_classifier.py")


if __name__ == '__main__':
    main()
