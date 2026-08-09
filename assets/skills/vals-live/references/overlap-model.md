# Dependency and overlap metadata

Vals records carry `dependencies` and `independence_class`; overlap warnings do not alter source values or invent an observed relationship. Facts not verified by the selected artifact use `certainty:"requirements_claim"` and retain null population/release plus an evidence placeholder rather than fabricated source evidence.

The declarative registry includes the required relationships:

- Artificial Analysis **Coding Agent Index** → DeepSWE, Terminal-Bench v2, SWE-Atlas-QnA (`direct_component`, `requirements_claim`).
- Vals → possible SWE-bench and Terminal-Bench populations (`possible_component`, `requirements_claim` unless the selected Vals methodology verifies an exact component).
- Vals Index is a derived composite when its published formula names components; preserve the exact formula, component versions, weights, denominator and subset selection.

A future router may issue `OVERLAP_DOUBLE_COUNTING_RISK` when joining these IDs. This source-local skill does not import Artificial Analysis or DeepSWE and does not compute an independence-adjusted score. Similar labels are never evidence of overlap.
