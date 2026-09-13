"""Row-level stores: data/decisions.parquet and data/outcomes.parquet.

Every run re-harvests the full corpus and upserts by anon_decision_id. Rows are
never deleted: a decision the RTB withdraws stays in the store (its
last_seen_run stops advancing) and the monotonic-growth check flags the drop.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from rtb.facets import APPLICANT, PROCESS, RENTAL_TYPE, TENANCY_STATUS, Combo

DECISION_COLUMNS = [
    "anon_decision_id",
    "applicant",
    "process",
    "rental_type",
    "tenancy_status",
    "dispute_type",
    "dispute_sub_type",
    "dispute_process",
    "tenancy_ended",
    "decision_date",
    "posting_date",
    "application_submitted_date",
    "previous_hearing_date",
    "previous_hearing_linking_type",
    "creation_method",
    "note_worthy",
    "materially_different",
    "search_result_summary",
    "first_seen_run",
    "last_seen_run",
]

OUTCOME_COLUMNS = [
    "anon_decision_id",
    "outcome_seq",
    "claim_code",
    "remedy_status",
    "remedy_sub_status",
    "remedy_type",
]

DATE_COLUMNS = ["decision_date", "posting_date", "application_submitted_date", "previous_hearing_date"]


def decision_rows(combo: Combo, decisions: list[dict], run_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Flatten raw API decisions into decision and outcome frames.

    Facet values come from the query combination, not the record: the record's
    own `tenancy_end` field is null in practice.
    """
    drows, orows = [], []
    for d in decisions:
        did = d["anon_decision_id"]
        drows.append({
            "anon_decision_id": did,
            "applicant": APPLICANT[combo.dispute_sub_type],
            "process": PROCESS[combo.dispute_process],
            "rental_type": RENTAL_TYPE[combo.dispute_type],
            "tenancy_status": TENANCY_STATUS[combo.tenancy_ended],
            "dispute_type": combo.dispute_type,
            "dispute_sub_type": combo.dispute_sub_type,
            "dispute_process": combo.dispute_process,
            "tenancy_ended": combo.tenancy_ended,
            "decision_date": d.get("decision_date"),
            "posting_date": d.get("posting_date"),
            "application_submitted_date": d.get("application_submitted_date"),
            "previous_hearing_date": d.get("previous_hearing_date"),
            "previous_hearing_linking_type": d.get("previous_hearing_linking_type"),
            "creation_method": d.get("creation_method"),
            "note_worthy": d.get("note_worthy"),
            "materially_different": d.get("materially_different"),
            "search_result_summary": d.get("search_result_summary"),
            "first_seen_run": run_id,
            "last_seen_run": run_id,
        })
        for seq, o in enumerate(d.get("posted_decision_outcomes") or []):
            orows.append({
                "anon_decision_id": did,
                "outcome_seq": seq,
                "claim_code": o.get("claim_code"),
                "remedy_status": o.get("remedy_status"),
                "remedy_sub_status": o.get("remedy_sub_status"),
                "remedy_type": o.get("remedy_type"),
            })
    return _typed_decisions(pd.DataFrame(drows, columns=DECISION_COLUMNS)), _typed_outcomes(
        pd.DataFrame(orows, columns=OUTCOME_COLUMNS)
    )


def _typed_decisions(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    for col in ["dispute_type", "dispute_sub_type", "dispute_process", "tenancy_ended",
                "previous_hearing_linking_type", "creation_method"]:
        df[col] = df[col].astype("Int64")
    for col in ["note_worthy", "materially_different"]:
        df[col] = df[col].astype("boolean")
    for col in ["anon_decision_id", "applicant", "process", "rental_type", "tenancy_status",
                "search_result_summary", "first_seen_run", "last_seen_run"]:
        df[col] = df[col].astype("string")
    return df


def _typed_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["anon_decision_id"] = df["anon_decision_id"].astype("string")
    for col in ["outcome_seq", "claim_code", "remedy_status", "remedy_sub_status", "remedy_type"]:
        df[col] = df[col].astype("Int64")
    return df


def _sort_key(ids: pd.Series) -> pd.Series:
    return pd.to_numeric(ids.str.extract(r"(\d+)", expand=False), errors="coerce")


class Store:
    def __init__(self, data_dir: Path):
        self.decisions_path = data_dir / "decisions.parquet"
        self.outcomes_path = data_dir / "outcomes.parquet"

    def load(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self.decisions_path.exists():
            dec = _typed_decisions(pd.read_parquet(self.decisions_path))
            out = _typed_outcomes(pd.read_parquet(self.outcomes_path))
        else:
            dec = _typed_decisions(pd.DataFrame(columns=DECISION_COLUMNS))
            out = _typed_outcomes(pd.DataFrame(columns=OUTCOME_COLUMNS))
        return dec, out

    @staticmethod
    def upsert(old_dec: pd.DataFrame, old_out: pd.DataFrame,
               new_dec: pd.DataFrame, new_out: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Newly harvested rows replace stored ones; stored rows not seen this run are kept."""
        first_seen = old_dec.set_index("anon_decision_id")["first_seen_run"]
        new_dec = new_dec.copy()
        prior = new_dec["anon_decision_id"].map(first_seen)
        new_dec["first_seen_run"] = prior.fillna(new_dec["first_seen_run"]).astype("string")

        fresh = set(new_dec["anon_decision_id"])
        kept_dec = old_dec[~old_dec["anon_decision_id"].isin(fresh)]
        kept_out = old_out[~old_out["anon_decision_id"].isin(fresh)]

        dec = pd.concat([kept_dec, new_dec], ignore_index=True)
        out = pd.concat([kept_out, new_out], ignore_index=True)
        dec = dec.sort_values("anon_decision_id", key=_sort_key, kind="stable").reset_index(drop=True)
        out = out.sort_values(["anon_decision_id", "outcome_seq"],
                              key=lambda s: _sort_key(s) if s.name == "anon_decision_id" else s,
                              kind="stable").reset_index(drop=True)
        return _typed_decisions(dec), _typed_outcomes(out)

    def save(self, dec: pd.DataFrame, out: pd.DataFrame) -> None:
        self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
        dec.to_parquet(self.decisions_path, index=False, compression="zstd")
        out.to_parquet(self.outcomes_path, index=False, compression="zstd")
