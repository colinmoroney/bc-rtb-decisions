# Test fixtures

`published_2026-09.csv` is the aggregate as published before this pipeline existed
(227 rows, 135,254 claims). `tests/test_published_figures.py` checks that the pipeline,
run over the committed store and cut back to the snapshot's posting-date cutoff, reproduces
it exactly, including the headline figures:

| measure (RTA only) | published |
|---|---:|
| Landlord applications, all claims | 78.6% |
| Tenant applications, all claims | 45.1% |
| Landlord direct requests | 84.5% |
| Tenant disputing a 10 Day Notice (claim codes 208 CNR, 230 CNR-MT) | 25.3% |

On 12 Sep 2026 a live harvest (45,434 decisions, last posted 2026-09-12T16:38Z) reproduced
this file exactly. The test's cutoff, `posting_date <= 2026-09-12T23:59:59Z`, selects that
same set from any later store, since a decision's posting date is fixed when it is posted.

Do not regenerate this file. It is a fixed reference point.
