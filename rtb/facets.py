"""The four mandatory facets and the 16 combinations the corpus is partitioned into.

The API parameter names do not mean what they say. The mapping below was
established empirically (13 Sep 2026) and verified by census reconciliation:
a wrong mapping silently returns a fraction of the corpus.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

# API parameter -> {value: label}. Labels match the published CSV columns.
RENTAL_TYPE = {1: "Home", 2: "ManufHome"}          # DisputeType
APPLICANT = {0: "Landlord", 1: "Tenant"}           # DisputeSubType
PROCESS = {1: "Participatory", 2: "DirectRequest"} # DisputeProcess
TENANCY_STATUS = {0: "InUnit", 1: "MovedOut"}      # TenancyEnded

# Rental type 1 is decided under the Residential Tenancy Act; 2 under the
# Manufactured Home Park Tenancy Act. Published statistics default to RTA only.
RTA_RENTAL_TYPE = 1


@dataclass(frozen=True, order=True)
class Combo:
    dispute_type: int
    dispute_sub_type: int
    dispute_process: int
    tenancy_ended: int

    @property
    def params(self) -> dict[str, int]:
        return {
            "DisputeType": self.dispute_type,
            "DisputeSubType": self.dispute_sub_type,
            "DisputeProcess": self.dispute_process,
            "TenancyEnded": self.tenancy_ended,
        }

    @property
    def key(self) -> str:
        return (
            f"{APPLICANT[self.dispute_sub_type]}/{PROCESS[self.dispute_process]}/"
            f"{RENTAL_TYPE[self.dispute_type]}/{TENANCY_STATUS[self.tenancy_ended]}"
        )


ALL_COMBOS: tuple[Combo, ...] = tuple(
    Combo(*values)
    for values in itertools.product(RENTAL_TYPE, APPLICANT, PROCESS, TENANCY_STATUS)
)
