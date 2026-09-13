"""Monthly harvest: census, full re-harvest, integrity checks, upsert, aggregate, publish.

Exit status 0 means the data outputs were written (possibly with warnings);
1 means an integrity check failed and nothing under data/, runs/ or README.md
was touched. Either way --status-file and a summary next to it are written for
the workflow to turn into a GitHub issue.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from rtb import aggregate, checks, report
from rtb.api import Client, ComboHarvest
from rtb.facets import ALL_COMBOS, RENTAL_TYPE, RTA_RENTAL_TYPE
from rtb.store import Store, decision_rows

log = logging.getLogger("rtb.run")


def harvest_all(client) -> list[ComboHarvest]:
    harvests = []
    for combo in ALL_COMBOS:
        census = client.census(combo)
        h = client.harvest(combo, census)
        if h.totals_seen and h.totals_seen != {census}:
            # Decisions were posted mid-harvest. Retry once against a fresh census.
            log.warning("%s moved during paging; retrying", combo.key)
            census = client.census(combo)
            h = client.harvest(combo, census)
        log.info("%-40s census %6d harvested %6d", combo.key, census, len(h.decisions))
        harvests.append(h)
    return harvests


def load_census_history(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"runs": []}


def main(argv: list[str] | None = None, client=None, now: datetime | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path("."), help="repository root")
    p.add_argument("--status-file", type=Path, default=Path(".cache/status.json"))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    root = args.root
    data_dir, runs_dir = root / "data", root / "runs"
    census_path = data_dir / "census.json"
    run_at = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    run_id = run_at.strftime("%Y-%m-%dT%H%MZ")

    client = client or Client()
    harvests = harvest_all(client)
    total = sum(len(h.decisions) for h in harvests)

    history = load_census_history(census_path)
    prev = history["runs"][-1] if history["runs"] else None
    prev_total = prev["total"] if prev else None
    prev_run_at = datetime.fromisoformat(prev["run_at"]) if prev else None

    result = checks.CheckResult()
    checks.census_reconciliation(harvests, result)
    checks.facet_consistency(harvests, result)
    checks.cross_combo_duplicates(harvests, result)
    checks.database_total_reconciliation(client.database_total, harvests, result)
    checks.monotonic_growth(prev_total, total, result)
    checks.plausible_delta(prev_total, prev_run_at, total, run_at, result)
    checks.unknown_enums(harvests, result)
    checks.schema_drift(client.envelope_keys, harvests, result)

    store_total = heads = agg = None
    if not result.errors:
        frames = [decision_rows(h.combo, h.decisions, run_id) for h in harvests]
        new_dec = pd.concat([f[0] for f in frames], ignore_index=True)
        new_out = pd.concat([f[1] for f in frames], ignore_index=True)
        store = Store(data_dir)
        old_dec, old_out = store.load()
        dec, out = Store.upsert(old_dec, old_out, new_dec, new_out)
        gone = len(dec) - total
        if gone > 0:
            result.warnings.append(f"{gone} decisions in the store were not returned by the API this run")
        store_total = len(dec)
        agg = aggregate.outcomes_by_claim(dec, out)
        heads = aggregate.headlines(agg)

    summary = report.run_summary(run_id, run_at, harvests, result, total, prev_total,
                                 client.database_total, store_total, heads, client.request_count)

    if not result.errors:
        store.save(dec, out)
        agg.to_csv(data_dir / "rtb_outcomes_by_claim.csv", index=False)
        history["runs"].append({
            "run_id": run_id,
            "run_at": run_at.isoformat(),
            "status": result.status,
            "total": total,
            "total_database_records": client.database_total,
            "combinations": [
                {"combination": h.combo.key, **h.combo.params, "expected": h.census, "harvested": len(h.decisions)}
                for h in harvests
            ],
        })
        census_path.write_text(json.dumps(history, indent=2) + "\n")
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{run_at:%Y-%m}.md").write_text(summary)
        rta = dec[dec["rental_type"] == RENTAL_TYPE[RTA_RENTAL_TYPE]]
        (root / "README.md").write_text(report.readme(
            run_at, len(dec), len(rta), heads, dec["decision_date"].min(), dec["decision_date"].max()))

    args.status_file.parent.mkdir(parents=True, exist_ok=True)
    args.status_file.write_text(json.dumps({
        "run_id": run_id, "status": result.status, "total": total,
        "errors": result.errors, "warnings": result.warnings,
    }, indent=2) + "\n")
    (args.status_file.parent / "summary.md").write_text(summary)

    print(summary)
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
