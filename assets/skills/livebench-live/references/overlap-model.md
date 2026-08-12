# Overlap model

- LiveBench Coding and Agentic Coding: separate release/category populations.
- Conceptual relationship to coding-agent work: retained as declarative dependency metadata with `certainty: requirements_claim`; observed category labels do not prove overlap with another benchmark’s rows.
- Adapter does not import Artificial Analysis or DeepSWE; never adjusts scores for overlap.
- Dependency objects preserve: source, index/benchmark name, canonical ID, relationship, population, release, certainty, source path.
- Future router may emit `OVERLAP_DOUBLE_COUNTING_RISK` when joining exact canonical IDs.
- Published LiveBench score and cost values remain source-local. Similar labels, model names, or token prices are not evidence of shared populations or interchangeable metrics.
