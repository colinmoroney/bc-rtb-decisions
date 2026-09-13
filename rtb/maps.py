"""Enum maps. Anything observed in the data that is not listed here is reported
loudly in the run summary (see checks.unknown_enums): BC amended the Residential
Tenancy Act in 2026 and new notice types will arrive as new claim codes.
"""
from __future__ import annotations

import json
from pathlib import Path

# Claim (issue) codes, from the issues_config the RTB's own PostedDecisions site
# loads. To refresh: fetch the site's config/*.json and replace claim_codes.json.
_CLAIMS = json.loads(Path(__file__).with_name("claim_codes.json").read_text())["codes"]
CLAIM_CODES: dict[int, dict] = {int(k): v for k, v in _CLAIMS.items()}
KNOWN_CLAIM_CODES: set[int] = set(CLAIM_CODES)


def claim_label(code: int) -> str | None:
    c = CLAIM_CODES.get(int(code))
    return f"{c['acronym']}: {c['title']}" if c else None


# CNR and CNR-MT (the "more time to dispute" variant).
TENANT_DISPUTE_10_DAY_NOTICE_CODES = (208, 230)

# remedy_status -> outcome bucket. Filled in from the harvest (see below).
REMEDY_STATUS: dict[int, str] = {}

KNOWN_REMEDY_SUB_STATUS: set[int] = set()
KNOWN_REMEDY_TYPE: set[int] = set()
