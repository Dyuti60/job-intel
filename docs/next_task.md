# Next task: Assam source expansion — mixed CMS document resolver

Implement only the first registry batch:

- `FREMAA_ASSAM`
- `ASDM_ASSAM`
- `PNRD_ASSAM`
- `DTE_ASSAM`

Create one reusable bounded `DATED_DOCUMENT_RESOLVER` by extending existing official-archive
primitives. It must classify listing rows before document fetch, apply
`AJI_HISTORY_LOOKBACK_MONTHS` to reliable dates, retain otherwise valid undated recruitments
conservatively, and exclude results, merit/selection lists, admit cards, interviews, verification,
appointments, cancellations, postponements, corrigenda/addenda alone, and extensions alone.

For each source, add small HTML fixtures proving recruitment discovery, lifecycle exclusion,
document URL resolution, deterministic Candidate identity, idempotent rediscovery, and handoff to
shared Advertisement-to-Post structuring. Activate a source only after one bounded non-persistent
official live validation succeeds. Do not implement the later registry batches in this task.
