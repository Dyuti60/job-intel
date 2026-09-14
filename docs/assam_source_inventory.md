# Official Assam recruitment source inventory

Inventory reviewed on 2026-09-14. “Implemented” means a deterministic adapter and scheduler entry
exist; it does not mean every historical PDF can be structured without Human Review. Official
authority pages are the only authoritative sources. The canonical historical window is the current
Asia/Kolkata calendar year plus the two preceding calendar years, inclusive (2024–2026 today).

## Implemented and enabled

| Code | Official endpoint | Family | Group / interval | Live validation |
| --- | --- | --- | --- | --- |
| APSC | `https://apsc.nic.in/` | custom recruitment portal | HIGH_PRIORITY / 6h | HTTP gateway returned 502 on 2026-09-14; fixture/CI coverage remains green |
| SLPRB_ASSAM | `https://slprbassam.in/` | authority-specific HTML table + PDF | HIGH_PRIORITY / 6h | HTTP gateway returned 502 on 2026-09-14; fixture/CI coverage remains green |
| DEE_ASSAM | `https://dee.assam.gov.in/portlets/recruitment-under-dee-assam` | document-list CMS + PDF | HIGH_PRIORITY / 12h | HTTP 200 on 2026-09-14; parser selected 4 in-window advertisements |
| DME_ASSAM | `https://dme.assam.gov.in/documents-detail/recruitment` | document-list CMS + PDF | NORMAL / 24h | HTTP 200 on 2026-09-14; parser selected 2 in-window advertisements |
| ASDMA_ASSAM | `https://asdma.assam.gov.in/resource/recruitment` | structured resource table + download | NORMAL / 24h | HTTP 200 on 2026-09-14; parser selected 42 in-window vacancies after lifecycle exclusions |

All adapters use bounded response sizes, connect/read timeouts, retry only transient failures, a
descriptive user agent, stable URL/hash identities, and conservative advertisement selection.
Results, merit/selection lists, answer keys, verification/interview schedules, admit cards,
appointments, cancellations, postponements, extensions, corrigenda, and addenda do not create new
jobs.

## Validated inventory awaiting a safe adapter extension

| Authority | Official endpoint | Likely family | Onboarding decision |
| --- | --- | --- | --- |
| NHM Assam | `https://nhm.assam.gov.in/latest/advertisement-for-various-posts-under-nhm-assam` | CMS detail page + PDF | defer until bounded archive enumeration is proven |
| Samagra Shiksha Axom | `https://ssa.assam.gov.in/information-services/recruitment-notice` | CMS link list/detail + PDF | defer; current links need deterministic detail-page traversal |
| P&RD / ASRLM | `https://asrlms.assam.gov.in/portlets/recruitment-career-1` | CMS link list/detail + PDF | defer; page mixes advertisements, results, and interview lists |
| Directorate of Agriculture | `https://diragri.assam.gov.in/resource/recruitment-1` | paginated resource list | defer until bounded pagination and download resolution are fixture-covered |
| FREMAA | `https://fremaa.assam.gov.in/portlets/recruitment-career` | document-list CMS + PDF | defer; many titles lack a reliable publication year |
| P&RD documents | `https://pnrd.assam.gov.in/documents/recruitment` | paginated document CMS | defer; category/archive behavior needs source-specific validation |
| Niyukti | `https://niyukti.assam.gov.in/` | recruitment portal | defer; application service is not a stable public advertisement index |

District administration pages, power entities, boards, universities, courts, and remaining
departments stay inventory candidates—not registered executable sources—until official ownership,
stable archive behavior, historical reach, document classification, and respectful polling bounds
are each confirmed. V2 may propose source candidates, but only an audited deterministic onboarding
change may enable them.

The ASDMA live check also fetched one selected official PDF (HTTP 200, 1,058,569 bytes) and
deterministically extracted four advertisement fields. It remained `LEGACY_UNSPLIT` because that
document did not expose a safely supported Post table; no Post was invented.
