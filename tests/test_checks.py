from datetime import datetime, timedelta, timezone

from rtb import checks
from rtb.api import ComboHarvest
from rtb.facets import Combo

T = datetime(2026, 11, 3, tzinfo=timezone.utc)


def test_delta_within_range_is_quiet():
    r = checks.CheckResult()
    checks.plausible_delta(45_000, T - timedelta(days=31), 46_400, T, r)
    assert r.status == "ok"


def test_delta_too_small_or_large_warns_but_does_not_fail():
    for new in (45_050, 52_000):
        r = checks.CheckResult()
        checks.plausible_delta(45_000, T - timedelta(days=30), new, T, r)
        assert r.status == "warn" and not r.errors


def test_delta_skipped_for_back_to_back_runs():
    r = checks.CheckResult()
    checks.plausible_delta(45_000, T - timedelta(hours=2), 45_000, T, r)
    assert r.status == "ok" and "skipped" in r.notes[0]


def test_monotonic_growth():
    r = checks.CheckResult()
    checks.monotonic_growth(45_000, 45_000, r)
    assert r.status == "ok"
    checks.monotonic_growth(45_000, 44_999, r)
    assert r.status == "fail"


def test_census_counts_unique_decisions_not_page_rows():
    combo = Combo(1, 0, 1, 0)
    h = ComboHarvest(combo=combo, census=3, decisions=[{"anon_decision_id": "a"}, {"anon_decision_id": "b"}],
                     duplicates=1, totals_seen={3})
    r = checks.CheckResult()
    checks.census_reconciliation([h], r)
    assert r.status == "fail" and "census 3, harvested 2" in r.errors[0]


def test_empty_combination_is_valid():
    h = ComboHarvest(combo=Combo(1, 1, 2, 0), census=0, decisions=[])
    r = checks.CheckResult()
    checks.census_reconciliation([h], r)
    assert r.status == "ok"
