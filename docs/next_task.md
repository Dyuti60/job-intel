# Next task: protected production release rehearsal

Rehearse the existing protected Public Release path on the intended host: validate protected
configuration, complete a build-only release, verify the coordinated backup and Alembic-head gate,
deploy the immutable public image, run the bounded public smoke checks, preview due sources, and
observe the first scheduled due-only run in Operations. Do not expose `app.main`, force
`--all-enabled`, mutate source coverage, or bypass the protected environment approval.

DHS/DME OCR is passive monitoring only. Revisit it only if a current, in-window image-only official
advertisement demonstrates production value; do not backfill historical scans or weaken
`AMBIGUOUS`/`LEGACY_UNSPLIT` safeguards.
