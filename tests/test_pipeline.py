"""End-to-end runs against the fake API: acceptance tests 2-4 and the failure modes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from rtb import run
from rtb.facets import Combo

T0 = datetime(2026, 10, 3, 10, 23, tzinfo=timezone.utc)


def do_run(tmp_path, client, now=T0) -> tuple[int, dict, str]:
    status_file = tmp_path / ".cache" / "status.json"
    code = run.main(["--root", str(tmp_path), "--status-file", str(status_file)], client=client, now=now)
    return code, json.loads(status_file.read_text()), (tmp_path / ".cache" / "summary.md").read_text()


def test_clean_run_reconciles_and_writes_outputs(tmp_path, records, client_for):
    code, status, summary = do_run(tmp_path, client_for(records))
    assert code == 0 and status["status"] == "ok", status
    assert status["total"] == len(records)
    for f in ["data/decisions.parquet", "data/outcomes.parquet", "data/rtb_outcomes_by_claim.csv",
              "data/census.json", "runs/2026-10.md", "README.md"]:
        assert (tmp_path / f).exists(), f
    census = json.loads((tmp_path / "data/census.json").read_text())["runs"][-1]
    assert len(census["combinations"]) == 16
    assert all(c["expected"] == c["harvested"] for c in census["combinations"])
    assert sum(c["expected"] == 0 for c in census["combinations"]) == 4  # empty is valid
    assert "**NO**" not in summary


def test_second_run_is_idempotent(tmp_path, records, client_for):
    do_run(tmp_path, client_for(records))
    dec1 = pd.read_parquet(tmp_path / "data/decisions.parquet")
    out1 = pd.read_parquet(tmp_path / "data/outcomes.parquet")
    csv1 = (tmp_path / "data/rtb_outcomes_by_claim.csv").read_bytes()

    code, status, _ = do_run(tmp_path, client_for(records), now=T0 + timedelta(hours=1))
    assert code == 0 and status["status"] == "ok", status
    dec2 = pd.read_parquet(tmp_path / "data/decisions.parquet")
    out2 = pd.read_parquet(tmp_path / "data/outcomes.parquet")
    assert len(dec2) == len(dec1) and len(out2) == len(out1)
    assert (tmp_path / "data/rtb_outcomes_by_claim.csv").read_bytes() == csv1
    assert (dec2["first_seen_run"] == dec1["first_seen_run"]).all()


def test_under_collection_fails_census(tmp_path, records, client_for):
    """A server that silently stops after one page must fail the run, not publish a short count."""
    code, status, summary = do_run(tmp_path, client_for(records, max_pages=1))
    assert code == 1 and status["status"] == "fail"
    assert any("Census mismatch for Landlord/DirectRequest/Home/InUnit" in e for e in status["errors"])
    assert not (tmp_path / "data/decisions.parquet").exists()


def test_corrupted_facet_mapping_fails(tmp_path, records, client_for, monkeypatch):
    """Swap DisputeProcess and TenancyEnded, the kind of mapping error that once returned
    21,694 of 45,728 records. Census and paging agree with each other, so the run must
    still fail on the database total and the per-record facet check."""
    def swapped(self):
        return {"DisputeType": self.dispute_type, "DisputeSubType": self.dispute_sub_type,
                "DisputeProcess": self.tenancy_ended, "TenancyEnded": self.dispute_process}
    monkeypatch.setattr(Combo, "params", property(swapped))
    code, status, _ = do_run(tmp_path, client_for(records))
    assert code == 1
    assert any("total_database_records" in e for e in status["errors"])
    assert any("disagree with the query facets" in e for e in status["errors"])
    assert not (tmp_path / "data/decisions.parquet").exists()


def test_unknown_claim_code_surfaces_in_summary(tmp_path, records, client_for):
    records[5]["posted_decision_outcomes"][0]["claim_code"] = 999
    code, status, summary = do_run(tmp_path, client_for(records))
    assert code == 0 and status["status"] == "warn"
    assert any("UNKNOWN claim_code" in w and "999" in w for w in status["warnings"])
    assert "| `claim_code` | 999 | 1 |" in summary
    assert "| `claim_code` | 999 | 1 |" in (tmp_path / "runs/2026-10.md").read_text()


def test_shrinking_corpus_fails_and_leaves_data_untouched(tmp_path, records, client_for):
    do_run(tmp_path, client_for(records))
    before = (tmp_path / "data/decisions.parquet").read_bytes()
    code, status, _ = do_run(tmp_path, client_for(records[:-3]), now=T0 + timedelta(days=30))
    assert code == 1
    assert any("Corpus shrank" in e for e in status["errors"])
    assert (tmp_path / "data/decisions.parquet").read_bytes() == before


def test_schema_drift_is_reported(tmp_path, records, client_for):
    records[0]["brand_new_field"] = "x"
    del records[1]["note_worthy"]
    code, status, _ = do_run(tmp_path, client_for(records))
    assert code == 0 and status["status"] == "warn"
    assert any("new decision field: brand_new_field" in w for w in status["warnings"])
    assert any("missing from some records: note_worthy" in w for w in status["warnings"])


def test_upsert_keeps_withdrawn_decisions_and_takes_new_values(tmp_path, records, client_for):
    do_run(tmp_path, client_for(records))
    changed = [dict(r) for r in records]
    changed[0] = {**changed[0], "note_worthy": True}
    extra = dict(records[-1], anon_decision_id="AnonDec-999999.pdf")
    code, _, _ = do_run(tmp_path, client_for(changed + [extra]), now=T0 + timedelta(days=30))
    dec = pd.read_parquet(tmp_path / "data/decisions.parquet").set_index("anon_decision_id")
    assert len(dec) == len(records) + 1
    assert bool(dec.loc[records[0]["anon_decision_id"], "note_worthy"]) is True
    assert dec.loc["AnonDec-999999.pdf", "first_seen_run"] != dec.loc[records[0]["anon_decision_id"], "first_seen_run"]
