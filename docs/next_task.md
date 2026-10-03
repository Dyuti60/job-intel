# Next task: Careerthora shared edge / deployment compatibility

Validate the Careerthora edge contract for the Jobs namespace without adding Prep or another state:
route only `/jobs`, `/jobs/*`, `/api/jobs/v1/*`, `/healthz`, and `/readyz` to the public Jobs runtime;
preserve canonical `https://careerthora.com` origins, private-route isolation, immutable deployment,
and the protected Environment approval path.

Do not implement Prep, West Bengal, Central jobs, source expansion, or a new domain model in that
milestone.
