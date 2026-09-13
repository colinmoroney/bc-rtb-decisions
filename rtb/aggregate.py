"""The published aggregate (rtb_outcomes_by_claim.csv) and headline figures.

Success rate = granted / (granted + dismissed). Settled and other outcomes
(withdrawn, not decided, etc.) sit outside the denominator.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from rtb import maps
from rtb.facets import RENTAL_TYPE, RTA_RENTAL_TYPE

GROUP_COLUMNS = ["applicant", "process", "rental_type", "tenancy_status", "claim_code"]
BUCKETS = ["granted", "dismissed", "settled", "other"]
AGGREGATE_COLUMNS = GROUP_COLUMNS + ["n"] + BUCKETS


def outcomes_by_claim(decisions: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """One row per facet combination and claim code, over the full store (all rental types)."""
    df = outcomes.merge(decisions[["anon_decision_id"] + GROUP_COLUMNS[:-1]], on="anon_decision_id", how="inner")
    df["bucket"] = df["remedy_status"].map(lambda v: maps.REMEDY_STATUS.get(v, "other") if pd.notna(v) else "other")
    counts = (
        df.groupby(GROUP_COLUMNS + ["bucket"], observed=True).size().unstack("bucket", fill_value=0)
        .reindex(columns=BUCKETS, fill_value=0)
    )
    counts.columns.name = None
    counts.insert(0, "n", counts.sum(axis=1))
    agg = counts.reset_index()
    agg["claim_code"] = agg["claim_code"].astype(int)
    agg = agg.sort_values(GROUP_COLUMNS, kind="stable").reset_index(drop=True)
    return agg[AGGREGATE_COLUMNS].astype({c: int for c in ["n"] + BUCKETS})


@dataclass(frozen=True)
class Headline:
    label: str
    granted: int
    dismissed: int

    @property
    def decided(self) -> int:
        return self.granted + self.dismissed

    @property
    def rate(self) -> float:
        return 100 * self.granted / self.decided if self.decided else float("nan")


def _headline(agg: pd.DataFrame, label: str, mask: pd.Series) -> Headline:
    sub = agg[mask]
    return Headline(label, int(sub["granted"].sum()), int(sub["dismissed"].sum()))


def headlines(agg: pd.DataFrame) -> list[Headline]:
    """Headline figures, RTA only (manufactured home park disputes excluded)."""
    rta = agg["rental_type"] == RENTAL_TYPE[RTA_RENTAL_TYPE]
    landlord = agg["applicant"] == "Landlord"
    tenant = agg["applicant"] == "Tenant"
    return [
        _headline(agg, "Landlord applications, all claims", rta & landlord),
        _headline(agg, "Tenant applications, all claims", rta & tenant),
        _headline(agg, "Landlord direct requests", rta & landlord & (agg["process"] == "DirectRequest")),
        _headline(agg, "Tenant disputing a 10 Day Notice",
                  rta & tenant & agg["claim_code"].isin(maps.TENANT_DISPUTE_10_DAY_NOTICE_CODES)),
    ]
