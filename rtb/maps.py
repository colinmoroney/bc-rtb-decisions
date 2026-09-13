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

# remedy_status -> outcome bucket. The public site does not ship labels for these.
# The assignment was derived on 12 Sep 2026 as the unique one reproducing every row
# of the published aggregate exactly (227 rows x 4 buckets, 135,254 claims).
# Occurrence counts at that date are given for scale.
REMEDY_STATUS: dict[int, str] = {
    1: "granted",     #  4,490
    2: "granted",     #  3,615
    3: "granted",     #    139
    4: "granted",     # 50,199
    5: "granted",     #  4,757
    6: "granted",     #  6,965
    10: "dismissed",  #  9,401
    11: "dismissed",  # 29,084
    13: "settled",    #     33
    14: "settled",    #     41
    15: "settled",    #  5,129
    16: "settled",    #  8,150
    17: "settled",    #     51
    18: "settled",    #  1,952
    19: "settled",    #    166
    0: "other",       #  3,665
    20: "other",      #  1,745
    21: "other",      #    161
    25: "other",      #  1,883
    30: "other",      #  3,628
}

KNOWN_REMEDY_SUB_STATUS: set[int] = {105, 106}
KNOWN_REMEDY_TYPE: set[int] = {0}
