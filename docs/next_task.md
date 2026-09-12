# T-007 — Explainable Confidence Scoring and Review Routing

## Objective

Build a deterministic field-level and candidate-revision-level confidence policy from persisted
Verification facts, with an explainable component breakdown and deterministic review-routing
metadata.

## Scope

T-007 will introduce deterministic confidence components, source-authority weighting,
support/contradiction penalties, evidence-completeness inputs, field confidence scores,
candidate/revision confidence aggregation, explainable confidence breakdowns, configurable review
thresholds, and deterministic `ReviewRequired` routing metadata.

Confidence must be reproducible from immutable verification outcomes, reason codes, evidence
assessments, source-class counts, conflicts, and completeness facts. The implementation must expose
why a score and routing decision were produced and must not use arbitrary AI-generated percentages.

## Boundaries

T-007 will not implement Human Review UI, human approval, Recruitment Master, publication, live
crawling, or LLM scoring.
