#!/usr/bin/env python3
"""
Xiphos Stress Test -- 55 defense-sector vendors spanning every risk tier,
country risk band, ownership structure, and edge case.

Usage:
  # Against local server (dev mode, no auth):
  python tests/stress_test.py

  # Against authenticated server:
  python tests/stress_test.py --url http://localhost:8080 --token <bearer_token>

  # Dry run (just print vendors, don't hit API):
  python tests/stress_test.py --dry-run
"""

import sys
import json
import time
import argparse
import urllib.request
import urllib.error

# ---- 55 Realistic Defense Sector Vendors ----

STRESS_VENDORS = [
    # === TIER: CLEAR (low risk, Five Eyes + NATO allies) ===
    {"name": "Lockheed Martin Corporation", "country": "US",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.99, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 75},
     "exec": {"known_execs": 20, "adverse_media": 0, "pep_execs": 0, "litigation_history": 2},
     "program": "weapons_system"},

    {"name": "Raytheon Technologies", "country": "US",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.98, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 50},
     "exec": {"known_execs": 18, "adverse_media": 0, "pep_execs": 0, "litigation_history": 1},
     "program": "weapons_system"},

    {"name": "BAE Systems plc", "country": "GB",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.97, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 60},
     "exec": {"known_execs": 15, "adverse_media": 0, "pep_execs": 0, "litigation_history": 1},
     "program": "weapons_system"},

    {"name": "Thales Group SA", "country": "FR",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.95, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 40},
     "exec": {"known_execs": 12, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "General Dynamics Corp", "country": "US",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.99, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 65},
     "exec": {"known_execs": 14, "adverse_media": 0, "pep_execs": 0, "litigation_history": 1},
     "program": "weapons_system"},

    {"name": "Saab AB", "country": "SE",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.96, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 85},
     "exec": {"known_execs": 10, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "Rheinmetall AG", "country": "DE",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.94, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 130},
     "exec": {"known_execs": 8, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "CAE Inc", "country": "CA",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.93, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 75},
     "exec": {"known_execs": 7, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "standard_industrial"},

    {"name": "Leonardo SpA", "country": "IT",
     "ownership": {"publicly_traded": True, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.90, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 75},
     "exec": {"known_execs": 11, "adverse_media": 1, "pep_execs": 1, "litigation_history": 2},
     "program": "weapons_system"},

    {"name": "Elbit Systems Ltd", "country": "IL",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.92, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 55},
     "exec": {"known_execs": 9, "adverse_media": 1, "pep_execs": 0, "litigation_history": 1},
     "program": "weapons_system"},

    # === TIER: MONITOR (moderate risk, some flags) ===
    {"name": "Hanwha Aerospace Co", "country": "KR",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.85, "shell_layers": 1, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 35},
     "exec": {"known_execs": 6, "adverse_media": 1, "pep_execs": 0, "litigation_history": 1},
     "program": "weapons_system"},

    {"name": "Singapore Technologies Engineering", "country": "SG",
     "ownership": {"publicly_traded": True, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.88, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 55},
     "exec": {"known_execs": 8, "adverse_media": 0, "pep_execs": 1, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "Bharat Electronics Limited", "country": "IN",
     "ownership": {"publicly_traded": True, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.80, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 70},
     "exec": {"known_execs": 5, "adverse_media": 1, "pep_execs": 2, "litigation_history": 0},
     "program": "standard_industrial"},

    {"name": "Denel SOC Ltd", "country": "ZA",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.70, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 30},
     "exec": {"known_execs": 4, "adverse_media": 2, "pep_execs": 1, "litigation_history": 1},
     "program": "weapons_system"},

    {"name": "Embraer Defense", "country": "BR",
     "ownership": {"publicly_traded": True, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.82, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 55},
     "exec": {"known_execs": 7, "adverse_media": 1, "pep_execs": 0, "litigation_history": 2},
     "program": "mission_critical"},

    {"name": "Turkish Aerospace Industries", "country": "TR",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.75, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 40},
     "exec": {"known_execs": 4, "adverse_media": 2, "pep_execs": 2, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Aselsan AS", "country": "TR",
     "ownership": {"publicly_traded": True, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.78, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 45},
     "exec": {"known_execs": 5, "adverse_media": 1, "pep_execs": 1, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "Tawazun Holding", "country": "AE",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.65, "shell_layers": 1, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 15},
     "exec": {"known_execs": 3, "adverse_media": 0, "pep_execs": 2, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "EDGE Group PJSC", "country": "AE",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.60, "shell_layers": 1, "pep_connection": True},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 5},
     "exec": {"known_execs": 4, "adverse_media": 0, "pep_execs": 3, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "PT Pindad", "country": "ID",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.55, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 40},
     "exec": {"known_execs": 3, "adverse_media": 1, "pep_execs": 1, "litigation_history": 0},
     "program": "standard_industrial"},

    # === TIER: ELEVATED (high risk, multiple flags) ===
    {"name": "Pakistan Ordnance Factories", "country": "PK",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.40, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 50},
     "exec": {"known_execs": 2, "adverse_media": 3, "pep_execs": 2, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Ukraine Defense Industry", "country": "UA",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.35, "shell_layers": 1, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 30},
     "exec": {"known_execs": 2, "adverse_media": 2, "pep_execs": 1, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Eurasian Mining Consortium", "country": "KZ",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.30, "shell_layers": 3, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 8},
     "exec": {"known_execs": 1, "adverse_media": 4, "pep_execs": 1, "litigation_history": 2},
     "program": "critical_infrastructure"},

    {"name": "Gulf Maritime Defence Solutions", "country": "BH",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.25, "shell_layers": 2, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 6},
     "exec": {"known_execs": 2, "adverse_media": 2, "pep_execs": 2, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "Caspian Industrial Group", "country": "AZ",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.25, "shell_layers": 3, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 2},
     "exec": {"known_execs": 1, "adverse_media": 3, "pep_execs": 1, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "Myanmar Defence Products", "country": "MM",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.15, "shell_layers": 2, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 10},
     "exec": {"known_execs": 1, "adverse_media": 5, "pep_execs": 1, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Saracen Global Trading", "country": "CY",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.10, "shell_layers": 4, "pep_connection": False},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 3},
     "exec": {"known_execs": 0, "adverse_media": 2, "pep_execs": 0, "litigation_history": 3},
     "program": "standard_industrial"},

    {"name": "Balkan Armaments doo", "country": "RS",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.20, "shell_layers": 2, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 12},
     "exec": {"known_execs": 2, "adverse_media": 3, "pep_execs": 1, "litigation_history": 1},
     "program": "weapons_system"},

    {"name": "Venezuelan Industrial Services CA", "country": "VE",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.20, "shell_layers": 1, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 15},
     "exec": {"known_execs": 1, "adverse_media": 4, "pep_execs": 2, "litigation_history": 0},
     "program": "standard_industrial"},

    # === TIER: HARD STOP (sanctioned countries, OFAC matches, extreme risk) ===
    {"name": "Rosoboronexport", "country": "RU",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.20, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 25},
     "exec": {"known_execs": 2, "adverse_media": 5, "pep_execs": 2, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Almaz-Antey Concern", "country": "RU",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.15, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 20},
     "exec": {"known_execs": 1, "adverse_media": 4, "pep_execs": 2, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "NORINCO Group", "country": "CN",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.30, "shell_layers": 2, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 40},
     "exec": {"known_execs": 3, "adverse_media": 3, "pep_execs": 3, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "AVIC International Holdings", "country": "CN",
     "ownership": {"publicly_traded": True, "state_owned": True, "beneficial_owner_known": True, "ownership_pct_resolved": 0.60, "shell_layers": 2, "pep_connection": True},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 70},
     "exec": {"known_execs": 5, "adverse_media": 3, "pep_execs": 3, "litigation_history": 1},
     "program": "mission_critical"},

    {"name": "Iran Electronics Industries", "country": "IR",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.10, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 30},
     "exec": {"known_execs": 1, "adverse_media": 5, "pep_execs": 1, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "DPRK Munitions Industry Dept", "country": "KP",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.0, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 0},
     "exec": {"known_execs": 0, "adverse_media": 5, "pep_execs": 0, "litigation_history": 0},
     "program": "nuclear_related"},

    {"name": "Syrian Scientific Studies Centre", "country": "SY",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.05, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 20},
     "exec": {"known_execs": 0, "adverse_media": 5, "pep_execs": 0, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "CATIC Beijing", "country": "CN",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.40, "shell_layers": 1, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 35},
     "exec": {"known_execs": 2, "adverse_media": 2, "pep_execs": 2, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Sudan Military Industrial Corp", "country": "SD",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.05, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 15},
     "exec": {"known_execs": 0, "adverse_media": 4, "pep_execs": 0, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Cuba Defence Enterprises", "country": "CU",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.10, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 40},
     "exec": {"known_execs": 1, "adverse_media": 3, "pep_execs": 1, "litigation_history": 0},
     "program": "standard_industrial"},

    # === EDGE CASES: Shell companies, mixed signals, unusual profiles ===
    {"name": "Horizon Strategic Consulting LLC", "country": "US",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.10, "shell_layers": 5, "pep_connection": False},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 1},
     "exec": {"known_execs": 0, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "intelligence_community"},

    {"name": "Pinnacle Logistics International", "country": "PA",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.05, "shell_layers": 6, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 2},
     "exec": {"known_execs": 0, "adverse_media": 1, "pep_execs": 0, "litigation_history": 5},
     "program": "standard_industrial"},

    {"name": "Nordic Precision Components AS", "country": "NO",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.85, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 25},
     "exec": {"known_execs": 3, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Pacific Rim Electronics Pty", "country": "AU",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.90, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": True, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 18},
     "exec": {"known_execs": 4, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "Adriatic Maritime Defence doo", "country": "HR",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.70, "shell_layers": 1, "pep_connection": False},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 10},
     "exec": {"known_execs": 2, "adverse_media": 0, "pep_execs": 0, "litigation_history": 1},
     "program": "standard_industrial"},

    {"name": "Al-Rashid Trading Group", "country": "SA",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.30, "shell_layers": 2, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 20},
     "exec": {"known_execs": 2, "adverse_media": 2, "pep_execs": 2, "litigation_history": 0},
     "program": "critical_infrastructure"},

    {"name": "Dragon Star Technologies Ltd", "country": "HK",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.15, "shell_layers": 3, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 5},
     "exec": {"known_execs": 1, "adverse_media": 2, "pep_execs": 1, "litigation_history": 0},
     "program": "mission_critical"},

    {"name": "Amazonia Resources LTDA", "country": "BR",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.60, "shell_layers": 1, "pep_connection": False},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 12},
     "exec": {"known_execs": 3, "adverse_media": 1, "pep_execs": 0, "litigation_history": 2},
     "program": "standard_industrial"},

    {"name": "Khartoum Engineering Works", "country": "SD",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.10, "shell_layers": 1, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 25},
     "exec": {"known_execs": 1, "adverse_media": 5, "pep_execs": 1, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Nordic Defence Group AB", "country": "SE",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.92, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 20},
     "exec": {"known_execs": 5, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Ankara Savunma Sistemleri AS", "country": "TR",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.70, "shell_layers": 1, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 15},
     "exec": {"known_execs": 3, "adverse_media": 1, "pep_execs": 1, "litigation_history": 0},
     "program": "weapons_system"},

    {"name": "Lagos Security Systems Ltd", "country": "NG",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.20, "shell_layers": 2, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 7},
     "exec": {"known_execs": 1, "adverse_media": 3, "pep_execs": 1, "litigation_history": 2},
     "program": "standard_industrial"},

    {"name": "Minsk Tractor Works", "country": "BY",
     "ownership": {"publicly_traded": False, "state_owned": True, "beneficial_owner_known": False, "ownership_pct_resolved": 0.30, "shell_layers": 0, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 70},
     "exec": {"known_execs": 2, "adverse_media": 3, "pep_execs": 2, "litigation_history": 0},
     "program": "standard_industrial"},

    # Borderline case: good company, bad country
    {"name": "Reliable Technical Services LLC", "country": "RU",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": True, "ownership_pct_resolved": 0.90, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": True, "has_cage": False, "has_duns": True, "has_tax_id": True, "has_audited_financials": True, "years_of_records": 20},
     "exec": {"known_execs": 5, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "standard_industrial"},

    # Borderline: bad company, good country
    {"name": "Shadow Creek Holdings LLC", "country": "US",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.0, "shell_layers": 7, "pep_connection": True},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": True, "has_audited_financials": False, "years_of_records": 0},
     "exec": {"known_execs": 0, "adverse_media": 5, "pep_execs": 0, "litigation_history": 8},
     "program": "intelligence_community"},

    # Minimal data vendor
    {"name": "Unknown Vendor Co", "country": "XX",
     "ownership": {"publicly_traded": False, "state_owned": False, "beneficial_owner_known": False, "ownership_pct_resolved": 0.0, "shell_layers": 0, "pep_connection": False},
     "data_quality": {"has_lei": False, "has_cage": False, "has_duns": False, "has_tax_id": False, "has_audited_financials": False, "years_of_records": 0},
     "exec": {"known_execs": 0, "adverse_media": 0, "pep_execs": 0, "litigation_history": 0},
     "program": "standard_industrial"},
]


def run_stress_test(base_url: str, token: str = "", dry_run: bool = False):
    """Run the stress test against the Xiphos API."""
    print(f"\n{'='*60}")
    print(f"  XIPHOS STRESS TEST -- {len(STRESS_VENDORS)} vendors")
    print(f"  Target: {base_url}")
    print(f"  Auth: {'token provided' if token else 'no auth (dev mode)'}")
    print(f"{'='*60}\n")

    results = {"clear": 0, "monitor": 0, "elevated": 0, "hard_stop": 0, "unknown": 0}
    errors = []
    total_time_ms = 0

    for i, vendor in enumerate(STRESS_VENDORS, 1):
        if dry_run:
            print(f"  [{i:02d}/{len(STRESS_VENDORS)}] {vendor['name']} ({vendor['country']}) -- DRY RUN")
            continue

        try:
            start = time.time()
            data = json.dumps(vendor).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}/api/cases",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    **({"Authorization": f"Bearer {token}"} if token else {}),
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req)
            elapsed_ms = int((time.time() - start) * 1000)
            total_time_ms += elapsed_ms

            body = json.loads(resp.read().decode("utf-8"))
            tier = body.get("calibrated", {}).get("calibrated_tier", "unknown")
            score = body.get("composite_score", 0)
            results[tier] = results.get(tier, 0) + 1

            tier_icon = {"clear": "✓", "monitor": "~", "elevated": "!", "hard_stop": "✗"}.get(tier, "?")
            print(f"  [{i:02d}/{len(STRESS_VENDORS)}] {tier_icon} {vendor['name'][:40]:<40} {vendor['country']}  score={score:3d}  tier={tier:<10}  {elapsed_ms}ms")

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            errors.append(f"{vendor['name']}: HTTP {e.code} -- {err_body[:100]}")
            print(f"  [{i:02d}/{len(STRESS_VENDORS)}] ERROR {vendor['name']}: HTTP {e.code}")
        except Exception as e:
            errors.append(f"{vendor['name']}: {str(e)}")
            print(f"  [{i:02d}/{len(STRESS_VENDORS)}] ERROR {vendor['name']}: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("  RESULTS")
    print(f"{'='*60}")
    total = sum(results.values())
    print(f"  Total vendors:   {total}")
    print(f"  Clear:           {results['clear']}")
    print(f"  Monitor:         {results['monitor']}")
    print(f"  Elevated:        {results['elevated']}")
    print(f"  Hard Stop:       {results['hard_stop']}")
    if results.get("unknown"):
        print(f"  Unknown:         {results['unknown']}")
    if total_time_ms > 0:
        print(f"  Total time:      {total_time_ms}ms ({total_time_ms/max(total,1):.0f}ms avg)")
    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for err in errors:
            print(f"    - {err}")
    else:
        print("\n  No errors.")
    print(f"{'='*60}\n")

    return len(errors) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Xiphos Stress Test")
    parser.add_argument("--url", default="http://localhost:8080", help="Base URL")
    parser.add_argument("--token", default="", help="Bearer token for auth")
    parser.add_argument("--dry-run", action="store_true", help="Just print, don't call API")
    args = parser.parse_args()

    success = run_stress_test(args.url, args.token, args.dry_run)
    sys.exit(0 if success else 1)
