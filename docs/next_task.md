# T-020 — Controlled Public Deployment and Release Automation

T-020 should deploy the hardened T-019 public ASGI/container surface to a selected controlled
hosting environment and make releases repeatable without exposing the trusted administration
runtime.

It should include:

- an explicit hosting target and infrastructure configuration for the public container
- automated immutable image build, provenance, vulnerability scanning, and release promotion
- managed TLS/domain configuration and strict routing of only public paths
- secure injection and rotation of the least-privilege public database credential
- deployment health gates, fixture-safe smoke tests, rollback automation, and release audit history
- verified PostgreSQL/raw-storage backup and isolated restore rehearsal
- production logging and bounded public availability monitoring without sensitive operational data
- a release checklist and evidence that `/review`, `/operations`, and internal `/api/v1` remain
  unreachable from the public network

T-020 must NOT implement eligibility matching, user accounts, alerts, preparation features, live
source expansion, automated Human Review, or mutable public APIs.

Do not implement T-020 now.
