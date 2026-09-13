"""Client for the RTB posted-decision search API.

Contract (undocumented, established empirically 13 Sep 2026):
- GET BASE_URL, unauthenticated; all four facet parameters are mandatory (else 400).
- `count` is page size, `index` is a zero-based page number; 400 when count + index > 500.
- Paging past the end returns an empty array.
- `file_url` carries a short-lived JWT for the PDF. We never fetch PDFs.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import requests

from rtb.facets import Combo

BASE_URL = "https://tenancydispute.gov.bc.ca/dms-services/posted-decision/arpi/posteddecision"
USER_AGENT = "rtb-harvest/1.0 (independent research; contact colinmoroney@gmail.com)"
PAGE_SIZE = 250
MAX_COUNT_PLUS_INDEX = 500
MIN_INTERVAL_S = 1.0

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


@dataclass
class ComboHarvest:
    combo: Combo
    census: int                      # total_available_records before paging
    decisions: list[dict]            # unique by anon_decision_id
    duplicates: int = 0              # records seen on more than one page
    requests: int = 0
    totals_seen: set[int] = field(default_factory=set)  # total_available_records per page


class Client:
    def __init__(self, session: requests.Session | None = None, min_interval: float = MIN_INTERVAL_S):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "application/json"
        self.min_interval = min_interval
        self._last = 0.0
        self.request_count = 0
        self.database_total: int | None = None
        self.envelope_keys: set[str] = set()

    def get(self, combo: Combo, count: int, index: int) -> dict:
        if count + index > MAX_COUNT_PLUS_INDEX:
            raise ApiError(f"count+index={count + index} exceeds server limit")
        params = {**combo.params, "count": count, "index": index}
        for attempt in range(5):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.request_count += 1
            try:
                resp = self.session.get(BASE_URL, params=params, timeout=60)
            except requests.RequestException as exc:
                log.warning("request failed (%s), attempt %d: %s", combo.key, attempt + 1, exc)
            else:
                if resp.status_code == 200:
                    body = resp.json()
                    self.envelope_keys |= body.keys()
                    self.database_total = body.get("total_database_records", self.database_total)
                    return body
                if resp.status_code < 500 and resp.status_code != 429:
                    raise ApiError(f"HTTP {resp.status_code} for {params}: {resp.text[:300]}")
                log.warning("HTTP %d (%s), attempt %d", resp.status_code, combo.key, attempt + 1)
            time.sleep(min(60, 5 * 2**attempt))
        raise ApiError(f"giving up after retries: {params}")

    def census(self, combo: Combo) -> int:
        return int(self.get(combo, count=1, index=0)["total_available_records"])

    def harvest(self, combo: Combo, census: int) -> ComboHarvest:
        out = ComboHarvest(combo=combo, census=census, decisions=[])
        if census == 0:
            return out
        seen: set[str] = set()
        max_index = MAX_COUNT_PLUS_INDEX - PAGE_SIZE
        for index in range(max_index + 1):
            body = self.get(combo, count=PAGE_SIZE, index=index)
            out.requests += 1
            out.totals_seen.add(int(body["total_available_records"]))
            page = body.get("posted_decisions") or []
            for d in page:
                did = d["anon_decision_id"]
                if did in seen:
                    out.duplicates += 1
                    continue
                seen.add(did)
                out.decisions.append(d)
            if len(page) < PAGE_SIZE:
                break
        else:
            log.error("%s: hit page ceiling (%d records) before end of results", combo.key, len(seen))
        return out
