# V1 operational activation checklist

V1 implementation includes shared deterministic Advertisement-to-Post structuring, canonical Post
naming, explicit safe single-Post creation, and an audited Human Review builder for ambiguous or
legacy-unsplit advertisements. Human-confirmed structures create immutable successor revisions and
use the normal Verification, Review, MasterPost, and public paths.

The remaining work is an operator-owned production activation,
not another application milestone.

- create and protect the GitHub `public-production` environment
- configure `AJI_PUBLIC_DATABASE_URL`, `AJI_BACKUP_DATABASE_URL`, `PUBLIC_HOSTNAME`, and
  `PUBLIC_BASE_URL` without storing credentials in the repository
- provision DNS/TLS ingress and restrict the private review/operations runtime to authorized staff
- run and retain a successful Restore Rehearsal against a disposable target
- run Public Release with `deploy=false`, review its scan and attestation, then make an explicit
  deployment decision
- validate public availability, private-route absence, backup manifest retention, and rollback
  evidence after activation

Source expansion and semantic interpretation improvements belong to V2 and must preserve the
deterministic onboarding and Human Review boundaries in `AGENTS.md`.
