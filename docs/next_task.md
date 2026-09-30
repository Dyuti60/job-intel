# Next task: resume authenticated protected production release rehearsal

From a repository-owner session with authenticated GitHub CLI or browser access, verify the
`public-production` required reviewer, `main` restriction, variables, and secret names without
printing values. Record the exact current `main` commit, then dispatch the existing Public Release
workflow for that commit with `deploy=false`. Record its run ID, immutable image digest, Trivy
result, and provenance result before requesting the separate `deploy=true` run and human
Environment approval.

Do not deploy through a parallel path, expose `app.main`, force `--all-enabled`, mutate source
coverage, or bypass protected approval. After an approved healthy deployment, run the existing
public smoke and due-only scheduler preview and record backup/release-audit evidence.

DHS/DME OCR is passive monitoring only. Revisit it only if a current, in-window image-only official
advertisement demonstrates production value; do not backfill historical scans or weaken
`AMBIGUOUS`/`LEGACY_UNSPLIT` safeguards.
