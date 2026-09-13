"""A fake RTB API that honours the real contract, and synthetic fixtures for it."""
from __future__ import annotations

import copy
import random
from datetime import datetime, timedelta, timezone

import pytest

from rtb import maps
from rtb.api import Client
from rtb.facets import ALL_COMBOS, Combo

# The four combinations that are legitimately empty in the real corpus.
EMPTY_COMBOS = {Combo(1, 1, 2, 0), Combo(2, 1, 2, 0), Combo(2, 0, 2, 1), Combo(2, 1, 2, 1)}
BIG_COMBO = Combo(1, 0, 2, 0)  # large enough to need three pages
FACET_PARAMS = ("DisputeType", "DisputeSubType", "DisputeProcess", "TenancyEnded")


class FakeResponse:
    def __init__(self, status_code: int, body=None, text: str = ""):
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        return self._body


class FakeApi:
    """Drop-in for requests.Session. Records carry a private `_tenancy_ended`
    because the real API returns `tenancy_end` as null."""

    def __init__(self, records: list[dict], max_pages: int | None = None):
        self.records = records
        self.max_pages = max_pages  # simulate a server that silently stops paging
        self.headers: dict[str, str] = {}

    def get(self, url, params=None, timeout=None):
        if any(p not in params for p in FACET_PARAMS):
            return FakeResponse(400, text="missing facet")
        count, index = int(params["count"]), int(params["index"])
        if count + index > 500:
            return FakeResponse(400, text="Please keep result sets small")
        match = [
            r for r in self.records
            if r["dispute_type"] == params["DisputeType"]
            and r["dispute_sub_type"] == params["DisputeSubType"]
            and r["dispute_process"] == params["DisputeProcess"]
            and r["_tenancy_ended"] == params["TenancyEnded"]
        ]
        page = [] if self.max_pages is not None and index >= self.max_pages else match[index * count:(index + 1) * count]
        page = [{k: v for k, v in copy.deepcopy(r).items() if k != "_tenancy_ended"} for r in page]
        return FakeResponse(200, {
            "total_database_records": len(self.records),
            "earliest_record_date": "2022-12-21T15:11:14.582Z",
            "total_available_records": len(match),
            "posted_decisions": page,
        })


def make_records(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    statuses = sorted(maps.REMEDY_STATUS)
    landlord_codes = sorted(c for c in maps.KNOWN_CLAIM_CODES if c < 200)
    tenant_codes = sorted(c for c in maps.KNOWN_CLAIM_CODES if c >= 200)
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    records, next_id = [], 1000
    for i, combo in enumerate(ALL_COMBOS):
        if combo in EMPTY_COMBOS:
            continue
        n = 620 if combo == BIG_COMBO else 20 + 9 * i
        codes = landlord_codes if combo.dispute_sub_type == 0 else tenant_codes
        for _ in range(n):
            decided = start + timedelta(days=rng.randint(0, 900))
            records.append({
                "decision_date": decided.isoformat(),
                "file_url": "https://example.invalid/pdf",
                "creation_method": 1,
                "dispute_type": combo.dispute_type,
                "dispute_sub_type": combo.dispute_sub_type,
                "dispute_process": combo.dispute_process,
                "tenancy_end": None,
                "_tenancy_ended": combo.tenancy_ended,
                "application_submitted_date": (decided - timedelta(days=60)).isoformat(),
                "previous_hearing_linking_type": None,
                "previous_hearing_date": None,
                "search_result_summary": "Synthetic.",
                "posting_date": (decided + timedelta(days=3)).isoformat(),
                "note_worthy": False,
                "materially_different": False,
                "anon_decision_id": f"AnonDec-{next_id}.pdf",
                "posted_decision_outcomes": [
                    {"remedy_type": 0, "remedy_status": rng.choice(statuses),
                     "remedy_sub_status": None, "claim_code": rng.choice(codes)}
                    for _ in range(rng.randint(1, 3))
                ],
            })
            next_id += 1
    return records


@pytest.fixture
def records() -> list[dict]:
    return make_records()


@pytest.fixture
def client_for():
    def build(records, **kw) -> Client:
        return Client(session=FakeApi(records, **kw), min_interval=0)
    return build
