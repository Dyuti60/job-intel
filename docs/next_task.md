# T-018 — Public Recruitment Web Interface

T-018 should implement a small, accessible, server-rendered public web interface over the T-017
Public Recruitment API/read service.

It should include:

- an Assam Government recruitment browse page with deterministic filters, ordering, and pagination
- a recruitment detail page showing current approved fields, application status and dates,
  vacancies, recruiting authority, and safe official-source links
- clear empty, unknown-status, closed, upcoming, and open states
- responsive, accessible HTML with no JavaScript framework or external asset dependency
- search-engine-safe metadata and canonical local routes without exposing internal workflow data
- tests proving the UI consumes only the T-017 approved public boundary and performs no mutations

T-018 must NOT implement eligibility matching, user profiles, alerts, preparation features, live
crawling, Human Review, mutable public operations, or Recruitment Master publishing.

Do not implement T-018 now.
