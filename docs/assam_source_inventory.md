# Assam official recruitment source registry

Reviewed 24 September 2026. This is the production-planning registry for materially relevant Assam
Government recruitment sources. A registry entry is not an enabled source. Only official authority
pages may be ingested; private aggregators and mirrors are excluded.

Discovery uses the rolling `AJI_HISTORY_LOOKBACK_MONTHS` window. Reliably dated notices older than
the cutoff are skipped; undated recruitment notices are retained conservatively. The window affects
future discovery, not retention of persisted history.

## Status and adapter-family vocabulary

- `ENABLED_VALIDATED`: registered, deterministically tested, and bounded-live-validated.
- `READY_FOR_ACTIVATION`: implementation and validation are complete but registration is disabled.
- `REQUIRES_EXISTING_ADAPTER_EXTENSION`: an existing family is the intended base, but the source
  still needs source-specific discovery configuration or bounded traversal/classification work.
- `REQUIRES_CUSTOM_ADAPTER`: the official shape needs a new reusable family or genuinely custom
  integration.
- `DISCOVERED_NOT_YET_VALIDATED`: official source found, but its stable recruitment surface or
  listing shape still needs one bounded validation pass.
- `EXCLUDED`: outside Assam Government scope or lacks an ingestible official recruitment feed.

Adapter families: **OFFICIAL_ARCHIVE** (listing/table to document), **CMS_DETAIL** (bounded listing
to detail to document), **DATED_DOCUMENT_RESOLVER** (mixed lifecycle listing with reliable date and
document resolution), **CUSTOM_PORTAL_API**, **CUSTOM_HTML_LISTING**, and **SPECIAL_CASE**.

## Authoritative registry

Scheduler values are recommendations for inactive sources. Lower numeric priority runs first.

| Code | Authority | Type | Official recruitment/listing URL | Freq. | Shape / recommended family | Status | Group / priority | Note or blocker |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `APSC` | Assam Public Service Commission | Commission | `https://apsc.nic.in/` | HIGH | portal + PDFs / CUSTOM_PORTAL_API | ENABLED_VALIDATED | HIGH_PRIORITY / 10 | Existing APSC adapter. |
| `SLPRB_ASSAM` | State Level Police Recruitment Board | Police board | `https://slprbassam.in/` | HIGH | HTML table + PDFs / OFFICIAL_ARCHIVE | ENABLED_VALIDATED | HIGH_PRIORITY / 20 | Existing official-archive configuration. |
| `DEE_ASSAM` | Directorate of Elementary Education | Directorate | `https://dee.assam.gov.in/portlets/recruitment-under-dee-assam` | HIGH | mixed document table / OFFICIAL_ARCHIVE | ENABLED_VALIDATED | HIGH_PRIORITY / 30 | Lifecycle filtering is required. |
| `DHS_ASSAM` | Directorate of Health Services | Directorate | `https://dhs.assam.gov.in/documents-detail/recruitment` | HIGH | document table + PDFs / OFFICIAL_ARCHIVE | ENABLED_VALIDATED | HIGH_PRIORITY / 35 | Existing official-archive configuration. |
| `DME_ASSAM` | Directorate of Medical Education | Directorate | `https://dme.assam.gov.in/documents-detail/recruitment` | HIGH | document table + PDFs / OFFICIAL_ARCHIVE | ENABLED_VALIDATED | NORMAL / 40 | Existing official-archive configuration. |
| `ASDMA_ASSAM` | Assam State Disaster Management Authority | Authority | `https://asdma.assam.gov.in/resource/recruitment` | PERIODIC | structured resources / OFFICIAL_ARCHIVE | ENABLED_VALIDATED | NORMAL / 60 | Existing structured-resource handling. |
| `DTE_ASSAM` | Directorate of Technical Education | Directorate | `https://dte.assam.gov.in/portlets/recruitment` | NORMAL | mixed CMS notices / DATED_DOCUMENT_RESOLVER | ENABLED_VALIDATED | HIGH_PRIORITY / 42 | Bounded live validation resolved one official document; safely routed LEGACY_UNSPLIT. |
| `AGRI_ASSAM` | Directorate of Agriculture | Directorate | `https://diragri.assam.gov.in/resource/recruitment-1` | NORMAL | listing to detail to document / CMS_DETAIL | REQUIRES_EXISTING_ADAPTER_EXTENSION | HIGH_PRIORITY / 45 | Live listing and `/node/` detail resolved, but the detail exposed no qualifying final recruitment document. |
| `NHM_ASSAM` | National Health Mission, Assam | Mission | `https://nhm.assam.gov.in/documents` | HIGH | filtered listing/detail/document / CMS_DETAIL | REQUIRES_EXISTING_ADAPTER_EXTENSION | HIGH_PRIORITY / 50 | Reachable official documents page emitted no qualifying recruitment detail links. |
| `ASRLM_ASSAM` | Assam State Rural Livelihoods Mission | Mission | `https://asrlms.assam.gov.in/portlets/recruitment-career` | NORMAL | mixed listing/detail/document / CMS_DETAIL | REQUIRES_EXISTING_ADAPTER_EXTENSION | NORMAL / 62 | Reachable official listing emitted no qualifying recruitment detail links; scheduler group remains NORMAL. |
| `FREMAA_ASSAM` | Flood and River Erosion Management Agency of Assam | Agency | `https://fremaa.assam.gov.in/portlets/recruitment-career` | NORMAL | mixed document table / DATED_DOCUMENT_RESOLVER | ENABLED_VALIDATED | NORMAL / 64 | Bounded live validation resolved one official document; safely routed LEGACY_UNSPLIT. |
| `DECT_ASSAM` | Directorate of Employment and Craftsmen Training | Directorate | `https://dect.assam.gov.in/portlets/recruitment-career-0` | NORMAL | mixed CMS/search listing / DATED_DOCUMENT_RESOLVER | REQUIRES_EXISTING_ADAPTER_EXTENSION | NORMAL / 58 | Includes job-fair and lifecycle material unrelated to authority vacancies. |
| `PNRD_ASSAM` | Panchayat and Rural Development | Department | `https://pnrd.assam.gov.in/documents/recruitment` | HIGH | dated document listing / DATED_DOCUMENT_RESOLVER | REQUIRES_EXISTING_ADAPTER_EXTENSION | HIGH_PRIORITY / 44 | Reachable, but the live listing emitted no qualifying document links to this resolver. |
| `SAMAGRA_ASSAM` | Samagra Shiksha, Assam | Mission | `https://ssa.assam.gov.in/information-services/detail/recruitment-portal-0` | HIGH | portal/detail links / CMS_DETAIL | REQUIRES_EXISTING_ADAPTER_EXTENSION | HIGH_PRIORITY / 48 | Reachable official portal page emitted no qualifying recruitment detail links. |
| `ASDM_ASSAM` | Assam Skill Development Mission | Mission | `https://asdm.assam.gov.in/portlets/recruitment-career` | NORMAL | document archive / DATED_DOCUMENT_RESOLVER | REQUIRES_EXISTING_ADAPTER_EXTENSION | NORMAL / 56 | Reachable, but the live listing emitted no qualifying document links to this resolver. |
| `SAMETI_ASSAM` | State Agricultural Management and Extension Training Institute | Institute | `https://sameti.assam.gov.in/resource/recruitment-notice` | PERIODIC | structured resources / OFFICIAL_ARCHIVE | REQUIRES_EXISTING_ADAPTER_EXTENSION | NORMAL / 72 | Validate resource metadata and date extraction before activation. |
| `DSE_ASSAM` | Directorate of Secondary Education | Directorate | `https://dse.assam.gov.in/` | HIGH | dispersed CMS notices / CUSTOM_HTML_LISTING | REQUIRES_CUSTOM_ADAPTER | HIGH_PRIORITY / 46 | No stable recruitment-only listing was confirmed. |
| `GHC_ASSAM` | Gauhati High Court recruitment relevant to Assam | Court | `https://ghconline.gov.in/index.php/recruitment-notices/` | HIGH | dated HTML listing + documents / SPECIAL_CASE | REQUIRES_CUSTOM_ADAPTER | HIGH_PRIORITY / 52 | Must restrict ingestion to Assam/Principal Seat recruitments. |
| `MHRB_ASSAM` | Medical and Health Recruitment Board, Assam | Board | `https://nhm.assam.gov.in/documents` | HIGH | documents hosted with NHM / CUSTOM_HTML_LISTING | REQUIRES_CUSTOM_ADAPTER | HIGH_PRIORITY / 54 | Needs authoritative MHRB-vs-NHM ownership classification. |
| `APDCL_ASSAM` | Assam Power Distribution Company Limited | PSU | `https://www.apdcl.org/` | NORMAL | careers portal / CUSTOM_HTML_LISTING | REQUIRES_CUSTOM_ADAPTER | NORMAL / 66 | Reachable homepage emitted no qualifying recruitment listing item; stable career endpoint remains unresolved. |
| `APGCL_ASSAM` | Assam Power Generation Corporation Limited | PSU | `https://www.apgcl.org/public/en/career/recruitments` | NORMAL | structured recruitment table / CUSTOM_HTML_LISTING | ENABLED_VALIDATED | NORMAL / 67 | Bounded live validation resolved one official document; safely routed LEGACY_UNSPLIT. |
| `AEGCL_ASSAM` | Assam Electricity Grid Corporation Limited | PSU | `https://www.aegcl.co.in/career-recruitment/` | NORMAL | recruitment table + documents / CUSTOM_HTML_LISTING | ENABLED_VALIDATED | NORMAL / 68 | Bounded live validation resolved one official document; safely routed LEGACY_UNSPLIT. |
| `AMTRON_ASSAM` | Assam Electronics Development Corporation | PSU | `https://recruitment.amtron.in/` | NORMAL | application/recruitment portal / CUSTOM_PORTAL_API | REQUIRES_CUSTOM_ADAPTER | NORMAL / 69 | Portal behavior and stable document identity need bounded validation. |
| `GAUHATI_UNIVERSITY` | Gauhati University | State university | `https://gauhati.ac.in/` | NORMAL | notices + application portal / CUSTOM_HTML_LISTING | REQUIRES_CUSTOM_ADAPTER | NORMAL / 74 | Reachable, but the bounded official surface exposed no qualifying in-window recruitment item/document. |
| `DIBRUGARH_UNIVERSITY` | Dibrugarh University | State university | `https://www.dibru.ac.in/categories/archive/recruitment-notices/2025/July` | NORMAL | dated archive pages / CUSTOM_HTML_LISTING | REQUIRES_CUSTOM_ADAPTER | NORMAL / 75 | Reachable, but the bounded archive/listing shape exposed no qualifying in-window recruitment item/document. |
| `COTTON_UNIVERSITY` | Cotton University | State university | `https://recruit.cottonuniversity.ac.in/` | NORMAL | application portal + notices / CUSTOM_PORTAL_API | REQUIRES_CUSTOM_ADAPTER | NORMAL / 76 | Reachable, but the bounded official portal/listing exposed no qualifying recruitment advertisement/document. |
| `AAU_ASSAM` | Assam Agricultural University | State university | `https://www.appl.aau.ac.in/recuitments/index.php` | NORMAL | custom recruitment portal / CUSTOM_PORTAL_API | REQUIRES_CUSTOM_ADAPTER | NORMAL / 77 | Preserve the authority's published `recuitments` URL spelling. |
| `ASTU_ASSAM` | Assam Science and Technology University | State university | `https://astu.ac.in/?page_id=110` | PERIODIC | WordPress listing + documents / CUSTOM_HTML_LISTING | REQUIRES_CUSTOM_ADAPTER | NORMAL / 78 | Reachable, but the bounded WordPress/listing surface exposed no qualifying in-window recruitment item/document. |
| `SLRC_ASSAM` | State Level Recruitment Commissions (ADRE) | Commission | `https://site.sebaonline.org/` | PERIODIC | campaign portals / SPECIAL_CASE | REQUIRES_CUSTOM_ADAPTER | HIGH_PRIORITY / 25 | Campaign URLs change; a stable authoritative advertisement archive is unresolved. |
| `AYUSH_ASSAM` | Directorate of AYUSH | Directorate | `https://ayush.assam.gov.in/` | PERIODIC | CMS latest/detail pages / CMS_DETAIL | DISCOVERED_NOT_YET_VALIDATED | NORMAL / 70 | Official recruitment details exist, but no stable recruitment index was confirmed. |
| `HOME_POLITICAL_ASSAM` | Home and Political Department | Department | `https://homeandpolitical.assam.gov.in/documents-detail/recruitment-notice` | PERIODIC | individual document detail / OFFICIAL_ARCHIVE | DISCOVERED_NOT_YET_VALIDATED | NORMAL / 80 | Detail page is official but is not yet a stable recurring listing. |
| `ASU_ASSAM` | Assam Skill University | State university | `https://asu.ac.in/` | PERIODIC | institution site / CUSTOM_HTML_LISTING | DISCOVERED_NOT_YET_VALIDATED | NORMAL / 82 | Recruitment section endpoint and recurrence need validation. |
| `SOIL_ASSAM` | Directorate of Soil Conservation | Directorate | `https://soildirectorate.assam.gov.in/` | PERIODIC | dispersed documents / CUSTOM_HTML_LISTING | DISCOVERED_NOT_YET_VALIDATED | NORMAL / 84 | Official advertisements were found, but no stable listing was confirmed. |
| `ASHB_ASSAM` | Assam State Housing Board | Board | `https://ashb.assam.gov.in/portlets/recruitment-and-career` | PERIODIC | service-regulation page only | EXCLUDED | NONE | No stable official vacancy feed is currently present. |
| `ASSAM_UNIVERSITY` | Assam University, Silchar | Central university | `https://www.aus.ac.in/employment-notification/` | NORMAL | official employment listing | EXCLUDED | NONE | Central university; outside Assam Government scope. |

## Counts

- Official sources inventoried: **35**.
- `ENABLED_VALIDATED`: **10**.
- `READY_FOR_ACTIVATION`: **0**; no inactive source has both deterministic tests and bounded live
  validation yet.
- `REQUIRES_EXISTING_ADAPTER_EXTENSION`: **8**.
- `REQUIRES_CUSTOM_ADAPTER`: **11**.
- `DISCOVERED_NOT_YET_VALIDATED`: **4**.
- `EXCLUDED`: **2**.

## Implementation roadmap

Each batch is a planning unit, not authorization to enable a source. Activation still requires
fixtures, deterministic discovery/lifecycle tests, idempotency tests, shared Post-structuring
handoff, and one bounded non-persistent live validation per source.

### Batch 1 — mixed Assam CMS document resolver

`FREMAA_ASSAM`, `ASDM_ASSAM`, `PNRD_ASSAM`, and `DTE_ASSAM`.

Completed 24 September 2026. One **DATED_DOCUMENT_RESOLVER** now handles bounded row/detail/document
resolution, reliable-date filtering, conservative undated recruitment handling, same-domain safety,
deduplication, and lifecycle exclusion. FREMAA and DTE passed bounded live validation and are
enabled. ASDM and PNRD remain disabled because their reachable live listings exposed no qualifying
document links to this resolver.

### Batch 2 — bounded CMS detail activation

`AGRI_ASSAM`, `NHM_ASSAM`, `ASRLM_ASSAM`, and `SAMAGRA_ASSAM`.

Completed 24 September 2026. **CMS_DETAIL** now provides bounded listing/detail/document controls,
surrounding-row date and lifecycle classification, canonical alias/document deduplication,
same-domain enforcement, and no-recursion behavior for all four configured sources. None was
activated: Agriculture reached an official detail without a qualifying final document; NHM, ASRLM,
and Samagra exposed no qualifying detail links in their single bounded live validations.

### Batch 3 — power-sector HTML family

`APDCL_ASSAM`, `APGCL_ASSAM`, and `AEGCL_ASSAM`.

Completed 24 September 2026. One bounded **CUSTOM_HTML_LISTING** family now reuses the shared dated
document resolver with power-authority URL, host-alias, path, and schedule configuration. APGCL and
AEGCL passed bounded live validation and are enabled; both safely routed LEGACY_UNSPLIT without
fabricated Posts. APDCL remains disabled because its reachable homepage exposed no qualifying
recruitment listing item.

### Batch 4 — state-institution listings

`GAUHATI_UNIVERSITY`, `DIBRUGARH_UNIVERSITY`, `COTTON_UNIVERSITY`, and `ASTU_ASSAM`.

Completed 24 September 2026. The bounded **CUSTOM_HTML_LISTING** family now has deterministic
institution configurations and fixtures covering cutoff, undated notices, lifecycle exclusion,
authority aliases, traversal bounds, idempotency, and shared Post structuring. None was activated:
all four official surfaces were reachable but exposed no qualifying recruitment item/document in
their single bounded live validations. Application portals remain supporting context and never
create Candidates by themselves.

### Later custom and special batches

- **CUSTOM_PORTAL_API**: `AMTRON_ASSAM`, `AAU_ASSAM`, and portal portions of university sources.
- **SPECIAL_CASE**: `GHC_ASSAM` (Assam-seat filtering) and `SLRC_ASSAM` (campaign identity).
- Validate the four discovered-only sources before assigning an implementation batch.
