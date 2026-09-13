"""Acceptance test 5: the pipeline reproduces the figures already published.

Runs against the committed store (data/*.parquet), so it is skipped until the
first harvest exists. The published snapshot (tests/fixtures/published_2026-09.csv)
predates later harvests, so the store is cut back to decisions posted on or before
the snapshot cutoff before comparing.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from rtb import aggregate

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "tests" / "fixtures" / "published_2026-09.csv"
DECISIONS = ROOT / "data" / "decisions.parquet"
OUTCOMES = ROOT / "data" / "outcomes.parquet"
# Last posting_date included in the published snapshot (see tests/fixtures/README.md).
SNAPSHOT_POSTED_BY = pd.Timestamp("2026-09-12T23:59:59Z")

pytestmark = pytest.mark.skipif(not DECISIONS.exists(), reason="no harvested store yet")


@pytest.fixture(scope="module")
def snapshot_agg() -> pd.DataFrame:
    dec = pd.read_parquet(DECISIONS)
    out = pd.read_parquet(OUTCOMES)
    dec = dec[dec["posting_date"] <= SNAPSHOT_POSTED_BY]
    return aggregate.outcomes_by_claim(dec, out[out["anon_decision_id"].isin(dec["anon_decision_id"])])


def test_headline_figures_match_publication(snapshot_agg):
    rates = {h.label: round(h.rate, 1) for h in aggregate.headlines(snapshot_agg)}
    assert rates == {
        "Landlord applications, all claims": 78.6,
        "Tenant applications, all claims": 45.1,
        "Landlord direct requests": 84.5,
        "Tenant disputing a 10 Day Notice": 25.3,
    }


def test_aggregate_matches_published_csv(snapshot_agg):
    published = pd.read_csv(PUBLISHED)
    pd.testing.assert_frame_equal(snapshot_agg.reset_index(drop=True), published, check_dtype=False)
