"""Integrity checks. A silent data error is worse than a failed run.

Severity:
- errors   fail the run: nothing is committed and an issue is opened.
- warnings do not fail the run, but open an issue and are listed in the run summary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from rtb.api import ComboHarvest
from rtb import maps

EXPECTED_ENVELOPE_FIELDS = {
    "total_database_records",
    "total_available_records",
    "earliest_record_date",
    "posted_decisions",
}

EXPECTED_DECISION_FIELDS = {
    "anon_decision_id",
    "decision_date",
    "posting_date",
    "application_submitted_date",
    "previous_hearing_date",
    "previous_hearing_linking_type",
    "dispute_type",
    "dispute_sub_type",
    "dispute_process",
    "tenancy_end",
    "creation_method",
    "note_worthy",
    "materially_different",
    "search_result_summary",
    "file_url",
    "posted_decision_outcomes",
}

EXPECTED_OUTCOME_FIELDS = {"claim_code", "remedy_status", "remedy_sub_status", "remedy_type"}

# ~46 new decisions a day (45,434 over ~33 months). Bounds are per 30 days.
DELTA_MIN_PER_30D = 200
DELTA_MAX_PER_30D = 5000
# Below this gap between runs (e.g. a manual re-run) the delta says nothing.
DELTA_MIN_ELAPSED_DAYS = 20


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unknown_enums: dict[str, dict[int, int]] = field(default_factory=dict)  # field -> {value: occurrences}
    schema_drift: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "fail" if self.errors else ("warn" if self.warnings else "ok")


def census_reconciliation(harvests: list[ComboHarvest], result: CheckResult) -> None:
    for h in harvests:
        got = len(h.decisions)
        if got != h.census:
            result.errors.append(
                f"Census mismatch for {h.combo.key}: census {h.census}, harvested {got} unique decisions"
            )
        if h.totals_seen and h.totals_seen != {h.census}:
            result.warnings.append(
                f"{h.combo.key}: total_available_records changed during paging "
                f"(census {h.census}, pages reported {sorted(h.totals_seen)})"
            )
        if h.duplicates:
            result.notes.append(f"{h.combo.key}: {h.duplicates} duplicate records across pages (deduplicated)")


def facet_consistency(harvests: list[ComboHarvest], result: CheckResult) -> None:
    """The record's own facet fields must agree with the query that returned it.

    `tenancy_end` is not checked: the API returns it as null.
    """
    for h in harvests:
        expected = {
            "dispute_type": h.combo.dispute_type,
            "dispute_sub_type": h.combo.dispute_sub_type,
            "dispute_process": h.combo.dispute_process,
        }
        bad = sum(1 for d in h.decisions if any(d.get(k) != v for k, v in expected.items()))
        if bad:
            result.errors.append(
                f"{h.combo.key}: {bad} records whose own facet fields disagree with the query facets"
            )


def cross_combo_duplicates(harvests: list[ComboHarvest], result: CheckResult) -> None:
    owner: dict[str, str] = {}
    clashes = 0
    for h in harvests:
        for d in h.decisions:
            did = d["anon_decision_id"]
            if did in owner and owner[did] != h.combo.key:
                clashes += 1
            owner.setdefault(did, h.combo.key)
    if clashes:
        result.errors.append(f"{clashes} decisions returned under more than one facet combination")


# The 16 combinations cover slightly fewer decisions than total_database_records
# (45,434 of 45,728 on 12 Sep 2026). A wrong facet mapping loses far more than
# this (21,694 of 45,728 in the incident that motivated these checks).
MIN_DATABASE_COVERAGE = 0.99


def database_total_reconciliation(database_total: int | None, harvests: list[ComboHarvest],
                                  result: CheckResult, prev_gap: int | None = None) -> int | None:
    """The 16 combinations should account for (almost) the whole database.

    Catches a wrong facet mapping that is internally consistent: census and
    paging agree, but a value matches nothing. Returns the gap for census.json.
    """
    total = sum(h.census for h in harvests)
    if database_total is None:
        result.warnings.append("API did not report total_database_records")
        return None
    gap = database_total - total
    coverage = total / database_total if database_total else 0.0
    if coverage < MIN_DATABASE_COVERAGE:
        result.errors.append(
            f"Facet combinations cover {total} of total_database_records {database_total} "
            f"({coverage:.1%}); expected at least {MIN_DATABASE_COVERAGE:.0%}. Check the facet mapping."
        )
    elif prev_gap is not None and gap != prev_gap:
        result.warnings.append(
            f"Decisions outside the 16 facet combinations changed from {prev_gap} to {gap} "
            f"(total_database_records {database_total}, combinations {total})"
        )
    else:
        result.notes.append(f"{gap} decisions in total_database_records fall outside the 16 facet combinations")
    return gap


def monotonic_growth(prev_total: int | None, total: int, result: CheckResult) -> None:
    if prev_total is not None and total < prev_total:
        result.errors.append(
            f"Corpus shrank: {total} decisions now vs {prev_total} at the previous run. "
            "Either the RTB withdrew decisions or the API changed; a human needs to look."
        )


def plausible_delta(prev_total: int | None, prev_run_at: datetime | None, total: int,
                    run_at: datetime, result: CheckResult) -> None:
    if prev_total is None or prev_run_at is None:
        result.notes.append("No previous run: growth checks skipped.")
        return
    delta = total - prev_total
    days = (run_at - prev_run_at).total_seconds() / 86400
    if days < DELTA_MIN_ELAPSED_DAYS:
        result.notes.append(
            f"Previous run was {days:.1f} days ago; delta plausibility check skipped (delta {delta:+d})."
        )
        return
    per_30d = delta * 30 / days
    if not DELTA_MIN_PER_30D <= per_30d <= DELTA_MAX_PER_30D:
        result.warnings.append(
            f"Implausible growth: {delta:+d} decisions over {days:.0f} days "
            f"(~{per_30d:.0f} per 30 days; expected {DELTA_MIN_PER_30D}-{DELTA_MAX_PER_30D})."
        )


def unknown_enums(harvests: list[ComboHarvest], result: CheckResult) -> None:
    known = {
        "claim_code": maps.KNOWN_CLAIM_CODES,
        "remedy_status": set(maps.REMEDY_STATUS),
        "remedy_sub_status": maps.KNOWN_REMEDY_SUB_STATUS,
        "remedy_type": maps.KNOWN_REMEDY_TYPE,
    }
    found: dict[str, dict[int, int]] = {k: {} for k in known}
    for h in harvests:
        for d in h.decisions:
            for o in d.get("posted_decision_outcomes") or []:
                for fld, values in known.items():
                    v = o.get(fld)
                    if v is not None and v not in values:
                        found[fld][v] = found[fld].get(v, 0) + 1
    result.unknown_enums = {k: v for k, v in found.items() if v}
    for fld, values in result.unknown_enums.items():
        listing = ", ".join(f"{v} (x{n})" for v, n in sorted(values.items()))
        result.warnings.append(f"UNKNOWN {fld} values: {listing}")


def schema_drift(envelope_keys: set[str], harvests: list[ComboHarvest], result: CheckResult) -> None:
    env_fields = set(envelope_keys)
    dec_fields: set[str] = set()
    out_fields: set[str] = set()
    missing_dec: set[str] = set()
    missing_out: set[str] = set()
    for h in harvests:
        for d in h.decisions:
            dec_fields |= d.keys()
            missing_dec |= EXPECTED_DECISION_FIELDS - d.keys()
            for o in d.get("posted_decision_outcomes") or []:
                out_fields |= o.keys()
                missing_out |= EXPECTED_OUTCOME_FIELDS - o.keys()
    drift = []
    if env_fields:
        drift += [f"new envelope field: {f}" for f in sorted(env_fields - EXPECTED_ENVELOPE_FIELDS)]
        drift += [f"missing envelope field: {f}" for f in sorted(EXPECTED_ENVELOPE_FIELDS - env_fields)]
    drift += [f"new decision field: {f}" for f in sorted(dec_fields - EXPECTED_DECISION_FIELDS)]
    drift += [f"decision field missing from some records: {f}" for f in sorted(missing_dec)]
    drift += [f"new outcome field: {f}" for f in sorted(out_fields - EXPECTED_OUTCOME_FIELDS)]
    drift += [f"outcome field missing from some records: {f}" for f in sorted(missing_out)]
    result.schema_drift = drift
    for line in drift:
        result.warnings.append(f"Schema drift: {line}")
