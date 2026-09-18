# Official Assam recruitment source coverage

Reviewed 18 September 2026. Only official authority pages are ingestion sources. Phase 1 keeps
onboarding deliberately small: a source is enabled only after its listing shape produces bounded,
classifiable recruitment documents through a tested adapter.

## Existing

| Source | Official recruitment URL | Authority type | Frequency | Format / adapter | Priority | Status |
| --- | --- | --- | --- | --- | --- | --- |
| APSC | `https://apsc.nic.in/` | Commission | frequent | HTML/PDF, custom portal | high | EXISTING |
| SLPRB Assam | `https://slprbassam.in/` | Police board | frequent | HTML table/PDF, official archive | high | EXISTING |
| DEE Assam | `https://dee.assam.gov.in/portlets/recruitment-under-dee-assam` | Department | recurring | document table/PDF, official archive | high | EXISTING |
| DME Assam | `https://dme.assam.gov.in/documents-detail/recruitment` | Department | recurring | document table/PDF, official archive | high | EXISTING |
| ASDMA Assam | `https://asdma.assam.gov.in/resource/recruitment` | Autonomous authority | periodic | structured table/download, official archive | normal | EXISTING |

## Newly onboarded

| Source | Official recruitment URL | Authority type | Frequency | Format / adapter | Priority | Status |
| --- | --- | --- | --- | --- | --- | --- |
| DHS Assam | `https://dhs.assam.gov.in/documents-detail/recruitment` | Department | frequent | document table/PDF, official archive | high | READY_FOR_ONBOARDING |

DHS uses a conservative 12-month-style window (current and immediately preceding calendar year),
12-hour polling, four requests per minute, and at most 20 advertisements per run. Results, lists,
admit cards, verification/interview schedules, appointments, cancellations, postponements,
extensions, corrigenda, and addenda are excluded as new jobs.

## Requires custom adapter

| Source | Official recruitment URL | Authority type | Frequency | Format / recommended family | Priority | Status |
| --- | --- | --- | --- | --- | --- | --- |
| DTE Assam | `https://dte.assam.gov.in/portlets/recruitment` | Department | recurring | mixed/undated archive; dated document resolver | high | REQUIRES_CUSTOM_ADAPTER |
| Directorate of Agriculture | `https://diragri.assam.gov.in/resource/recruitment-1` | Department | recurring | listing to detail to PDF; bounded detail traversal | high | REQUIRES_CUSTOM_ADAPTER |
| DSE Assam | `https://dse.assam.gov.in/` | Department | frequent | mixed CMS; recruitment-index adapter | high | REQUIRES_CUSTOM_ADAPTER |
| NHM Assam | `https://nhm.assam.gov.in/latest/advertisement-for-various-posts-under-nhm-assam` | Mission | frequent | CMS detail/archive; bounded archive adapter | high | REQUIRES_CUSTOM_ADAPTER |
| Gauhati High Court | `https://ghconline.gov.in/index.php/recruitment-notices/` | Constitutional court | frequent | custom HTML listing/PDF with Assam filtering | high | REQUIRES_CUSTOM_ADAPTER |
| ASRLM | `https://asrlms.assam.gov.in/portlets/recruitment-career-1` | Mission | recurring | mixed listing/detail/PDF; lifecycle-aware traversal | normal | REQUIRES_CUSTOM_ADAPTER |
| FREMAA | `https://fremaa.assam.gov.in/portlets/recruitment-career` | Autonomous agency | recurring | undated mixed document table; dated document resolver | specialized | REQUIRES_CUSTOM_ADAPTER |
| DECT Assam | `https://dect.assam.gov.in/portlets/recruitment-career-0` | Department | periodic | undated mixed document table; dated document resolver | normal | REQUIRES_CUSTOM_ADAPTER |

## Next high-priority batch

Implement one bounded reusable CMS detail-traversal family and validate it first against Directorate
of Agriculture and NHM. DTE/DSE and Gauhati High Court should follow only with their required dated
archive and authority-scope rules. Until then these sources remain inventory entries, not executable
scheduler registrations.
