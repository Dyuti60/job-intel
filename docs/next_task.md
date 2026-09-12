# T-011 — First Live Official Source Adapter: APSC

## Objective

Connect the existing trusted pipeline to the first real Assam Government recruitment source by
implementing one narrowly defined APSC recruitment or notification flow.

## Scope

T-011 should implement:

- source seeding and registration for APSC
- an APSC-specific discovery adapter
- HTTP fetching with bounded timeouts and retries
- recruitment or notification listing discovery
- SourceDocument persistence
- deterministic NEW / UNCHANGED / CHANGED detection
- a controlled raw-content persistence strategy
- safe parsing of the selected APSC page or document type
- generation of RecruitmentCandidate revisions and CandidateFields
- extraction Evidence creation
- no direct Verification truth assumptions

The initial adapter should support one narrowly defined real APSC recruitment/notification flow
rather than attempting all APSC content.

## Boundaries

T-011 must not automate Human Review or schedule recurring crawling.
