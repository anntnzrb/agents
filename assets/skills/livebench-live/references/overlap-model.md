# Overlap model

LiveBench Coding and Agentic Coding are separate release/category populations. Their conceptual relationship to coding-agent work is retained as declarative dependency metadata with `certainty: requirements_claim`; observed category labels do not prove overlap with another benchmark's rows.

The adapter does not import Artificial Analysis or DeepSWE and never adjusts scores for overlap. It preserves dependency objects with source, index/benchmark name, canonical ID, relationship, population, release, certainty, and source path. A future router may emit `OVERLAP_DOUBLE_COUNTING_RISK` when joining exact canonical IDs.

Published LiveBench score and cost values remain source-local. Similar labels, model names, or token prices are not evidence of shared populations or interchangeable metrics.
