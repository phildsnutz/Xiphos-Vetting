#!/usr/bin/env python3
"""
Multi-source sanctions list sync engine for Xiphos.

Downloads and normalizes sanctioned entity data from multiple free,
publicly available international sanctions lists:

  1. US OFAC SDN       -- Treasury Dept Specially Designated Nationals
  2. UK Sanctions List -- FCDO consolidated sanctions (CSV)
  3. EU Financial Sanctions -- European Commission consolidated list (XML)
  4. UN Security Council -- Consolidated sanctions list (XML)
  5. OpenSanctions     -- Aggregated dataset (JSON bulk, non-commercial free)

All entities are normalized into a common SanctionRecord schema and stored
in SQLite for Jaro-Winkler fuzzy screening.

Usage:
    python sanctions_sync.py                    # Sync all sources
    python sanctions_sync.py --sources ofac,uk  # Sync specific sources
    python sanctions_sync.py --status           # Show current DB stats
    python sanctions_sync.py --dry-run          # Preview without writing
"""

import csv
import io
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SOURCES = {
    "ofac": {
        "label": "US OFAC SDN",
        "url": "https://www.treasury.gov/ofac/downloads/sdn.xml",
        "format": "xml",
    },
    "uk": {
        "label": "UK Sanctions List (FCDO)",
        "url": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv",
        "format": "csv",
    },
    "eu": {
        "label": "EU Financial Sanctions",
        "url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
        "format": "xml",
    },
    "un": {
        "label": "UN Security Council",
        "url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "format": "xml",
    },
    "opensanctions": {
        "label": "OpenSanctions (sanctions subset)",
        "url": "https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json",
        "format": "jsonl",
    },
}

USER_AGENT = "Xiphos-Vetting/2.0 (sanctions-sync; +https://github.com/phildsnutz/Xiphos-Vetting)"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SanctionRecord:
    """Normalized sanctions entry from any source."""
    source: str             # ofac, uk, eu, un, opensanctions
    source_uid: str         # unique ID within that source
    name: str               # primary name
    aliases: list[str] = field(default_factory=list)
    entity_type: str = ""   # individual, entity, vessel, aircraft
    country: str = ""       # ISO-2 country code
    program: str = ""       # sanctions program / regime
    list_type: str = ""     # SDN, SSI, CAATSA, etc.
    remarks: str = ""
    date_listed: str = ""

# ---------------------------------------------------------------------------
# Database layer (sanctions-specific)
# ---------------------------------------------------------------------------

def _get_sanctions_db_path() -> str:
    """Sanctions DB lives alongside the main Xiphos DB."""
    base = os.environ.get("XIPHOS_DB_PATH", os.path.join(os.path.dirname(__file__), "xiphos.db"))
    return os.path.join(os.path.dirname(base), "sanctions.db")


@contextmanager
def _get_conn():
    conn = sqlite3.connect(_get_sanctions_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_sanctions_db():
    """Create the sanctions tables."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sanctions_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_uid TEXT NOT NULL,
                name TEXT NOT NULL,
                name_upper TEXT NOT NULL,
                entity_type TEXT DEFAULT '',
                country TEXT DEFAULT '',
                program TEXT DEFAULT '',
                list_type TEXT DEFAULT '',
                remarks TEXT DEFAULT '',
                date_listed TEXT DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source, source_uid)
            );

            CREATE TABLE IF NOT EXISTS sanctions_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL REFERENCES sanctions_entities(id) ON DELETE CASCADE,
                alias TEXT NOT NULL,
                alias_upper TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                entities_count INTEGER NOT NULL DEFAULT 0,
                aliases_count INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ok',
                error_msg TEXT DEFAULT '',
                synced_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_se_source ON sanctions_entities(source);
            CREATE INDEX IF NOT EXISTS idx_se_name ON sanctions_entities(name_upper);
            CREATE INDEX IF NOT EXISTS idx_sa_alias ON sanctions_aliases(alias_upper);
            CREATE INDEX IF NOT EXISTS idx_sa_entity ON sanctions_aliases(entity_id);
        """)


def _bulk_upsert(conn: sqlite3.Connection, records: list[SanctionRecord]) -> tuple[int, int]:
    """Insert or update a batch of sanction records. Returns (entities, aliases)."""
    entity_count = 0
    alias_count = 0

    for rec in records:
        # Upsert entity
        conn.execute("""
            INSERT INTO sanctions_entities (source, source_uid, name, name_upper, entity_type,
                                            country, program, list_type, remarks, date_listed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source, source_uid) DO UPDATE SET
                name=excluded.name, name_upper=excluded.name_upper,
                entity_type=excluded.entity_type, country=excluded.country,
                program=excluded.program, list_type=excluded.list_type,
                remarks=excluded.remarks, date_listed=excluded.date_listed,
                updated_at=datetime('now')
        """, (rec.source, rec.source_uid, rec.name, rec.name.upper().strip(),
              rec.entity_type, rec.country, rec.program, rec.list_type,
              rec.remarks, rec.date_listed))

        entity_count += 1

        # Get the entity row id
        row = conn.execute(
            "SELECT id FROM sanctions_entities WHERE source=? AND source_uid=?",
            (rec.source, rec.source_uid)
        ).fetchone()
        if not row:
            continue
        eid = row["id"]

        # Replace aliases
        conn.execute("DELETE FROM sanctions_aliases WHERE entity_id=?", (eid,))
        for alias in rec.aliases:
            if alias and alias.upper().strip() != rec.name.upper().strip():
                conn.execute(
                    "INSERT INTO sanctions_aliases (entity_id, alias, alias_upper) VALUES (?, ?, ?)",
                    (eid, alias, alias.upper().strip())
                )
                alias_count += 1

    return entity_count, alias_count


def get_all_sanctions() -> list[dict]:
    """Load all sanctions entities + aliases for screening."""
    with _get_conn() as conn:
        entities = conn.execute("""
            SELECT id, source, source_uid, name, entity_type, country, program, list_type
            FROM sanctions_entities
        """).fetchall()

        result = []
        for e in entities:
            aliases_rows = conn.execute(
                "SELECT alias FROM sanctions_aliases WHERE entity_id=?", (e["id"],)
            ).fetchall()
            result.append({
                "name": e["name"],
                "aliases": [a["alias"] for a in aliases_rows],
                "source": e["source"],
                "source_uid": e["source_uid"],
                "entity_type": e["entity_type"],
                "country": e["country"],
                "program": e["program"],
                "list_type": e["list_type"],
            })
        return result


def get_sync_status() -> dict:
    """Return sync statistics."""
    with _get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM sanctions_entities").fetchone()[0]
        total_aliases = conn.execute("SELECT COUNT(*) FROM sanctions_aliases").fetchone()[0]

        by_source = {}
        rows = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM sanctions_entities GROUP BY source"
        ).fetchall()
        for r in rows:
            by_source[r["source"]] = r["cnt"]

        last_sync = {}
        rows = conn.execute("""
            SELECT source, MAX(synced_at) as last_sync, status
            FROM sync_log GROUP BY source
        """).fetchall()
        for r in rows:
            last_sync[r["source"]] = {"last_sync": r["last_sync"], "status": r["status"]}

        return {
            "total_entities": total,
            "total_aliases": total_aliases,
            "by_source": by_source,
            "last_sync": last_sync,
        }


# ---------------------------------------------------------------------------
# HTTP download helper
# ---------------------------------------------------------------------------

def _download(url: str, label: str, max_retries: int = 2) -> bytes:
    """Download a URL with retries and proper user-agent."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(max_retries + 1):
        try:
            print(f"    Downloading {label}...", end=" ", flush=True)
            with urllib.request.urlopen(req, timeout=120) as resp:
                # Handle redirects (OFAC uses S3 presigned URLs)
                data = resp.read()
                size_kb = len(data) / 1024
                print(f"{size_kb:.0f} KB")
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"retry in {wait}s ({e})")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Failed to download {label} after {max_retries + 1} attempts: {e}")


# ---------------------------------------------------------------------------
# Parsers (one per source)
# ---------------------------------------------------------------------------

def parse_ofac_xml(data: bytes) -> list[SanctionRecord]:
    """Parse OFAC SDN XML (schema: sdnList > sdnEntry)."""
    records = []
    root = ET.fromstring(data)

    # Handle namespace -- OFAC XML has a default namespace
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    for entry in root.findall(f".//{ns}sdnEntry"):
        uid_el = entry.find(f"{ns}uid")
        uid = uid_el.text.strip() if uid_el is not None and uid_el.text else ""

        # Name
        first = entry.find(f"{ns}firstName")
        last = entry.find(f"{ns}lastName")
        first_text = first.text.strip() if first is not None and first.text else ""
        last_text = last.text.strip() if last is not None and last.text else ""
        name = f"{first_text} {last_text}".strip() if first_text else last_text

        if not name:
            continue

        # Type
        sdn_type_el = entry.find(f"{ns}sdnType")
        sdn_type = sdn_type_el.text.strip().lower() if sdn_type_el is not None and sdn_type_el.text else "entity"

        # Program
        programs = []
        for p in entry.findall(f".//{ns}program"):
            if p.text:
                programs.append(p.text.strip())
        program = "; ".join(programs)

        # Aliases
        aliases = []
        for aka in entry.findall(f".//{ns}aka"):
            aka_first = aka.find(f"{ns}firstName")
            aka_last = aka.find(f"{ns}lastName")
            af = aka_first.text.strip() if aka_first is not None and aka_first.text else ""
            al = aka_last.text.strip() if aka_last is not None and aka_last.text else ""
            alias = f"{af} {al}".strip() if af else al
            if alias:
                aliases.append(alias)

        # Country from address
        country = ""
        addr = entry.find(f".//{ns}address")
        if addr is not None:
            c_el = addr.find(f"{ns}country")
            if c_el is not None and c_el.text:
                country = c_el.text.strip()[:2].upper()

        # Remarks
        remarks_el = entry.find(f"{ns}remarks")
        remarks = remarks_el.text.strip()[:500] if remarks_el is not None and remarks_el.text else ""

        records.append(SanctionRecord(
            source="ofac", source_uid=f"OFAC-{uid}",
            name=name, aliases=aliases,
            entity_type=sdn_type, country=country,
            program=program, list_type="SDN",
            remarks=remarks,
        ))

    return records


def parse_uk_csv(data: bytes) -> list[SanctionRecord]:
    """Parse UK Sanctions List CSV.

    The UK CSV has a metadata header row followed by column headers on row 2.
    Real columns include: Unique ID, OFSI Group ID, Name 6, Name 1, Name 2, etc.
    """
    records = []
    seen_uids: dict[str, SanctionRecord] = {}

    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    # Find the actual header row (contains "Unique ID" or "Name 6")
    header_idx = 0
    for i, line in enumerate(lines[:10]):
        if "Unique ID" in line or "Name 6" in line:
            header_idx = i
            break
    else:
        # Try skipping the first row (metadata row) and use row 2
        header_idx = 1

    # Rebuild CSV from the real header onwards
    csv_text = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(csv_text))

    for row in reader:
        group_id = (row.get("OFSI Group ID", "") or row.get("Unique ID", "")).strip()
        if not group_id:
            continue

        # Name 6 = entity/full name, Name 1 = surname, Name 2 = first name
        name6 = (row.get("Name 6", "") or "").strip()
        name1 = (row.get("Name 1", "") or "").strip()
        name2 = (row.get("Name 2", "") or "").strip()

        if name6:
            name = name6
        elif name1:
            name = f"{name2} {name1}".strip() if name2 else name1
        else:
            continue

        entity_type_raw = (row.get("Type of entity", "") or row.get("Group Type", "") or "").strip().lower()
        if "individual" in entity_type_raw:
            entity_type = "individual"
        else:
            entity_type = "entity"

        country = ""
        for ckey in ["Nationality(/ies)", "Address Country", "Country of birth"]:
            val = (row.get(ckey, "") or "").strip()
            if val:
                country = val[:2].upper()
                break

        regime = (row.get("Regime Name", "") or row.get("Regime", "") or "").strip()
        uid = (row.get("Unique ID", "") or group_id).strip()
        date_listed = (row.get("Date Designated", "") or row.get("Listed On", "") or "").strip()

        # Build aliases from non-Latin name and alternate Name fields
        aliases = []
        nls = (row.get("Name non-latin script", "") or "").strip()
        if nls and nls != name:
            aliases.append(nls)
        # If Name 6 is primary but Name 1+2 form a different string, add as alias
        if name6 and name1:
            alt = f"{name2} {name1}".strip() if name2 else name1
            if alt and alt != name:
                aliases.append(alt)

        # Deduplicate by group_id (multiple rows per entity for aliases/addresses)
        if group_id in seen_uids:
            existing = seen_uids[group_id]
            # This row might be an alias entry
            name_type = (row.get("Name type", "") or "").strip().lower()
            if "alias" in name_type or "aka" in name_type:
                if name and name not in existing.aliases and name != existing.name:
                    existing.aliases.append(name)
            for a in aliases:
                if a not in existing.aliases and a != existing.name:
                    existing.aliases.append(a)
            continue

        rec = SanctionRecord(
            source="uk", source_uid=f"UK-{uid}",
            name=name, aliases=aliases,
            entity_type=entity_type, country=country,
            program=regime, list_type="UK-SANCTIONS",
            date_listed=date_listed,
        )
        seen_uids[group_id] = rec
        records.append(rec)

    return records


def parse_eu_xml(data: bytes) -> list[SanctionRecord]:
    """Parse EU Financial Sanctions consolidated list XML (1.1 schema)."""
    records = []
    root = ET.fromstring(data)

    # EU XML uses: <WHOLE><ENTITY> structure
    for entity in root.iter():
        if entity.tag.upper() in ("ENTITY", "WHOLELIST"):
            continue

        # Look for SubjectType tags
        if "SubjectType" in entity.tag or entity.tag == "ENTITY":
            pass

    # More robust: iterate all children looking for entity entries
    # EU 1.1 schema: sanctionEntity elements
    for entry in root.iter():
        tag = entry.tag.split("}")[-1] if "}" in entry.tag else entry.tag

        if tag not in ("sanctionEntity", "ENTITY"):
            continue

        # Extract logicalId or designationDetails
        logical_id = entry.get("logicalId", "") or entry.get("euReferenceNumber", "")

        # Name extraction
        names = []
        for name_alias in entry.iter():
            ntag = name_alias.tag.split("}")[-1] if "}" in name_alias.tag else name_alias.tag
            if ntag in ("wholeName", "nameAlias", "lastName", "firstName"):
                text = name_alias.text
                if text:
                    names.append(text.strip())
            if ntag == "nameAlias":
                wn = name_alias.get("wholeName", "")
                if wn:
                    names.append(wn.strip())

        if not names:
            continue

        primary_name = names[0]
        aliases = list(set(n for n in names[1:] if n != primary_name))

        # Subject type
        subj_type_el = entry.find(".//{*}subjectType")
        etype = "entity"
        if subj_type_el is not None:
            code = (subj_type_el.get("code", "") or (subj_type_el.text or "")).lower()
            if "person" in code or "individual" in code:
                etype = "individual"

        # Regulation
        reg_el = entry.find(".//{*}regulation")
        programme = ""
        if reg_el is not None:
            prog_el = reg_el.find(".//{*}programme")
            if prog_el is not None and prog_el.text:
                programme = prog_el.text.strip()

        uid = logical_id or f"EU-{hash(primary_name) & 0xFFFFFF:06x}"

        records.append(SanctionRecord(
            source="eu", source_uid=f"EU-{uid}",
            name=primary_name, aliases=aliases,
            entity_type=etype, program=programme,
            list_type="EU-SANCTIONS",
        ))

    return records


def parse_un_xml(data: bytes) -> list[SanctionRecord]:
    """Parse UN Security Council consolidated sanctions list XML."""
    records = []
    root = ET.fromstring(data)

    # UN XML: <CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL> and <ENTITIES><ENTITY>
    for section_tag, etype in [("INDIVIDUAL", "individual"), ("ENTITY", "entity")]:
        for entry in root.iter(section_tag):
            # UID
            dataid = entry.find("DATAID")
            uid = dataid.text.strip() if dataid is not None and dataid.text else ""

            # Name
            if etype == "individual":
                first = entry.find("FIRST_NAME")
                second = entry.find("SECOND_NAME")
                third = entry.find("THIRD_NAME")
                parts = []
                for el in [first, second, third]:
                    if el is not None and el.text:
                        parts.append(el.text.strip())
                name = " ".join(parts)
            else:
                first = entry.find("FIRST_NAME")
                name = first.text.strip() if first is not None and first.text else ""

            if not name:
                continue

            # Aliases (INDIVIDUAL_ALIAS or ENTITY_ALIAS containers with ALIAS_NAME children)
            aliases = []
            for alias_tag in ["INDIVIDUAL_ALIAS", "ENTITY_ALIAS"]:
                for alias_el in entry.iter(alias_tag):
                    alias_name = alias_el.find("ALIAS_NAME")
                    if alias_name is not None and alias_name.text:
                        a = alias_name.text.strip()
                        if a and a != name:
                            aliases.append(a)
            # Also check NAME_ORIGINAL_SCRIPT
            orig = entry.find("NAME_ORIGINAL_SCRIPT")
            if orig is not None and orig.text:
                o = orig.text.strip()
                if o and o != name:
                    aliases.append(o)

            # Country
            country = ""
            nationality = entry.find("NATIONALITY")
            if nationality is not None:
                val = nationality.find("VALUE")
                if val is not None and val.text:
                    country = val.text.strip()[:2].upper()

            # Committee (program)
            un_list = entry.find("UN_LIST_TYPE")
            program = un_list.text.strip() if un_list is not None and un_list.text else ""

            # Listed on
            listed = entry.find("LISTED_ON")
            date_listed = listed.text.strip() if listed is not None and listed.text else ""

            # Comments
            comments_el = entry.find("COMMENTS1")
            remarks = comments_el.text.strip()[:500] if comments_el is not None and comments_el.text else ""

            records.append(SanctionRecord(
                source="un", source_uid=f"UN-{uid}",
                name=name, aliases=aliases,
                entity_type=etype, country=country,
                program=program, list_type="UN-CONSOLIDATED",
                remarks=remarks, date_listed=date_listed,
            ))

    return records


def parse_opensanctions_jsonl(data: bytes) -> list[SanctionRecord]:
    """Parse OpenSanctions FtM JSONL bulk export (sanctions subset)."""
    records = []
    text = data.decode("utf-8", errors="replace")

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # FtM schema: {"id": "...", "schema": "LegalEntity", "properties": {...}}
        schema = obj.get("schema", "")
        props = obj.get("properties", {})

        # Only keep entities and people
        if schema not in ("LegalEntity", "Company", "Organization", "Person", "Thing"):
            continue

        names = props.get("name", [])
        if not names:
            continue

        primary_name = names[0]
        aliases = props.get("alias", []) + names[1:]
        aliases = list(set(a for a in aliases if a != primary_name))

        entity_type = "individual" if schema == "Person" else "entity"
        countries = props.get("country", [])
        country = countries[0][:2].upper() if countries else ""

        # Topics tell us what kind of sanctions
        topics = props.get("topics", [])
        program = "; ".join(topics) if topics else ""

        # Source datasets
        datasets = obj.get("datasets", [])
        list_type = "; ".join(datasets[:3]) if datasets else "opensanctions"

        records.append(SanctionRecord(
            source="opensanctions", source_uid=obj.get("id", ""),
            name=primary_name, aliases=aliases[:20],  # cap aliases
            entity_type=entity_type, country=country,
            program=program, list_type=list_type,
        ))

    return records


# Map source keys to parser functions
PARSERS = {
    "ofac": parse_ofac_xml,
    "uk": parse_uk_csv,
    "eu": parse_eu_xml,
    "un": parse_un_xml,
    "opensanctions": parse_opensanctions_jsonl,
}


# ---------------------------------------------------------------------------
# Main sync orchestrator
# ---------------------------------------------------------------------------

def sync_source(source_key: str, dry_run: bool = False) -> dict:
    """Download and parse a single source. Returns stats."""
    if source_key not in SOURCES:
        return {"error": f"Unknown source: {source_key}"}

    src = SOURCES[source_key]
    t0 = time.time()
    result = {"source": source_key, "label": src["label"], "status": "ok"}

    try:
        data = _download(src["url"], src["label"])
        parser = PARSERS[source_key]
        records = parser(data)
        result["entities_parsed"] = len(records)
        result["sample"] = [r.name for r in records[:5]]

        if dry_run:
            result["status"] = "dry_run"
            alias_count = sum(len(r.aliases) for r in records)
            result["aliases_parsed"] = alias_count
        else:
            with _get_conn() as conn:
                e_count, a_count = _bulk_upsert(conn, records)
                result["entities_written"] = e_count
                result["aliases_written"] = a_count

                # Log the sync
                conn.execute("""
                    INSERT INTO sync_log (source, entities_count, aliases_count, duration_ms, status)
                    VALUES (?, ?, ?, ?, 'ok')
                """, (source_key, e_count, a_count, int((time.time() - t0) * 1000)))

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

        if not dry_run:
            try:
                with _get_conn() as conn:
                    conn.execute("""
                        INSERT INTO sync_log (source, entities_count, aliases_count, duration_ms, status, error_msg)
                        VALUES (?, 0, 0, ?, 'error', ?)
                    """, (source_key, int((time.time() - t0) * 1000), str(e)))
            except Exception:
                pass

    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result


def sync_all(source_keys: Optional[list[str]] = None, dry_run: bool = False) -> list[dict]:
    """Sync all (or specified) sources. Returns list of results."""
    keys = source_keys or list(SOURCES.keys())
    results = []

    print(f"\n{'='*60}")
    print(f"  XIPHOS Sanctions Sync -- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Sources: {', '.join(keys)}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    for key in keys:
        print(f"  [{key.upper()}] {SOURCES[key]['label']}")
        r = sync_source(key, dry_run=dry_run)
        if r["status"] == "ok":
            print(f"    -> {r.get('entities_written', r.get('entities_parsed', 0))} entities, "
                  f"{r.get('aliases_written', r.get('aliases_parsed', 0))} aliases "
                  f"({r['duration_ms']}ms)")
        elif r["status"] == "dry_run":
            print(f"    -> {r['entities_parsed']} entities parsed (dry run, not written)")
        else:
            print(f"    -> ERROR: {r.get('error', 'unknown')}")
        results.append(r)
        print()

    # Summary
    total_e = sum(r.get("entities_written", r.get("entities_parsed", 0)) for r in results)
    ok_count = sum(1 for r in results if r["status"] in ("ok", "dry_run"))
    err_count = sum(1 for r in results if r["status"] == "error")

    print(f"  Summary: {total_e} entities from {ok_count} sources ({err_count} errors)")

    if not dry_run:
        status = get_sync_status()
        print(f"  Database total: {status['total_entities']} entities, {status['total_aliases']} aliases")

    print()
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Xiphos multi-source sanctions sync")
    parser.add_argument("--sources", type=str, default="",
                        help="Comma-separated source keys (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Download and parse but don't write to DB")
    parser.add_argument("--status", action="store_true",
                        help="Show current sanctions DB status")
    parser.add_argument("--list-sources", action="store_true",
                        help="List available sources")
    args = parser.parse_args()

    # Initialize DB
    init_sanctions_db()

    if args.list_sources:
        print("\nAvailable sanctions sources:")
        for key, src in SOURCES.items():
            print(f"  {key:18s} {src['label']}")
        return

    if args.status:
        status = get_sync_status()
        print(f"\nSanctions Database Status:")
        print(f"  Total entities: {status['total_entities']}")
        print(f"  Total aliases:  {status['total_aliases']}")
        print(f"\n  By source:")
        for src, count in status["by_source"].items():
            label = SOURCES.get(src, {}).get("label", src)
            print(f"    {label:35s} {count:>8,}")
        print(f"\n  Last sync:")
        for src, info in status["last_sync"].items():
            label = SOURCES.get(src, {}).get("label", src)
            print(f"    {label:35s} {info['last_sync']}  [{info['status']}]")
        return

    sources = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else None
    sync_all(source_keys=sources, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
