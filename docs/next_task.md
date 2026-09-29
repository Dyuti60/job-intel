# Next task: DHS and DME degraded-extraction hardening

Use a small representative set of persisted DHS/DME SourceDocuments from the 29 September staged
run to diagnose the confirmed sparse extraction warnings. Improve only reusable official-archive
extraction behavior supported by those documents, preserving `LEGACY_UNSPLIT` whenever Post ownership
cannot be established safely.

Do not rerun all enabled sources, broaden source coverage, weaken lifecycle filtering, or alter
Review/Public Readiness/Master rules. Add focused fixtures for each confirmed extraction shape, run
one bounded non-persistent validation per affected source, and retain Human Review fallback for
unsupported documents.
