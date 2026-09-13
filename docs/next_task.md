# V1-M3 — Confidence V2 and separate review routing

Preserve every Confidence V1 assessment unchanged and add deterministic, explainable Confidence V2
over verified advertisement and post facts.

The milestone should include:

- immutable `V2` confidence assessments with an explicit component breakdown
- reliability components for authoritative source quality, extraction method/reliability,
  authoritative support, supporting evidence, conflicts, ambiguity, and completeness
- a separately versioned, persisted Human Review routing assessment
- routing for conflicts, ambiguous post splits/details, unclear critical meaning, uncertain
  vacancy/category mapping, and values that may belong to the wrong Post
- no review solely because an optional field is absent
- no publication decision embedded in either confidence or routing
- post-aware field and revision summaries with deterministic fixtures and API/worker coverage

Do not reinterpret, update, or delete V1 rows. Do not publish Posts to Master in this milestone.
