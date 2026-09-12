# T-015 — GitHub Actions Scheduled Pipeline Execution

T-015 must make the real T-013 pipeline executable manually and on a schedule from GitHub Actions using a trusted self-hosted runner connected to the persistent local/V0 PostgreSQL and raw-content storage.

T-015 must include:

- self-hosted runner execution
- workflow_dispatch
- scheduled execution
- GitHub Actions concurrency control
- application/database overlap protection
- persistent runtime configuration
- external persistent raw-storage root
- environment/secrets handling
- Alembic upgrade before pipeline execution
- T-013 pipeline invocation
- PipelineRun history using GITHUB_ACTION/SCHEDULED trigger metadata
- operational summary in GitHub Actions
- safe handling of Human Review-required results
- documentation for installing/running the Windows self-hosted runner as a service

It must NOT expose the local Human Review UI publicly.

Do not implement T-015 in T-014.
