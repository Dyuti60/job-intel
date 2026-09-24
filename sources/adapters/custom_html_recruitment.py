from dataclasses import dataclass

from app.models.source_registry import AuthorityType
from sources.adapters.dated_document_resolver import (
    DatedDocumentResolverAdapter,
    DatedDocumentSource,
)


@dataclass(frozen=True)
class CustomHtmlListingSource(DatedDocumentSource):
    """Configuration for a bounded authority-owned HTML recruitment listing."""


class CustomHtmlListingAdapter(DatedDocumentResolverAdapter):
    """Bounded HTML listing/detail/document traversal using shared archive extraction."""


CUSTOM_HTML_SOURCE_CANDIDATES = {
    "APDCL_ASSAM": CustomHtmlListingSource(
        source_code="APDCL_ASSAM",
        authority_code="APDCL_ASSAM",
        authority_name="Assam Power Distribution Company Limited",
        authority_type=AuthorityType.PSU,
        listing_url="https://www.apdcl.org/",
        adapter_key="custom_html_listing_apdcl",
        organization_name="Assam Power Distribution Company Limited",
        priority=66,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("www.apdcl.org", "apdcl.org"),
        detail_path_prefixes=("/website/", "/career/", "/recruitment/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
    "APGCL_ASSAM": CustomHtmlListingSource(
        source_code="APGCL_ASSAM",
        authority_code="APGCL_ASSAM",
        authority_name="Assam Power Generation Corporation Limited",
        authority_type=AuthorityType.PSU,
        listing_url="https://www.apgcl.org/public/en/career/recruitments",
        adapter_key="custom_html_listing_apgcl",
        organization_name="Assam Power Generation Corporation Limited",
        priority=67,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("www.apgcl.org", "apgcl.org"),
        detail_path_prefixes=("/public/en/career/", "/career/", "/recruitment/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
    "AEGCL_ASSAM": CustomHtmlListingSource(
        source_code="AEGCL_ASSAM",
        authority_code="AEGCL_ASSAM",
        authority_name="Assam Electricity Grid Corporation Limited",
        authority_type=AuthorityType.PSU,
        listing_url="https://www.aegcl.co.in/career-recruitment/",
        adapter_key="custom_html_listing_aegcl",
        organization_name="Assam Electricity Grid Corporation Limited",
        priority=68,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("www.aegcl.co.in", "aegcl.co.in"),
        detail_path_prefixes=("/career-recruitment/", "/career/", "/recruitment/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
    "GAUHATI_UNIVERSITY": CustomHtmlListingSource(
        source_code="GAUHATI_UNIVERSITY",
        authority_code="GAUHATI_UNIVERSITY",
        authority_name="Gauhati University",
        authority_type=AuthorityType.UNIVERSITY,
        listing_url="https://gauhati.ac.in/",
        adapter_key="custom_html_listing_gauhati_university",
        organization_name="Gauhati University",
        priority=74,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("gauhati.ac.in", "www.gauhati.ac.in"),
        detail_path_prefixes=("/recruitment/", "/notifications/", "/notice/", "/career/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
    "DIBRUGARH_UNIVERSITY": CustomHtmlListingSource(
        source_code="DIBRUGARH_UNIVERSITY",
        authority_code="DIBRUGARH_UNIVERSITY",
        authority_name="Dibrugarh University",
        authority_type=AuthorityType.UNIVERSITY,
        listing_url="https://www.dibru.ac.in/categories/archive/recruitment-notices/2025/July",
        adapter_key="custom_html_listing_dibrugarh_university",
        organization_name="Dibrugarh University",
        priority=75,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("www.dibru.ac.in", "dibru.ac.in", "oldweb.dibru.ac.in"),
        detail_path_prefixes=("/categories/", "/recruitment/", "/notifications/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
    "COTTON_UNIVERSITY": CustomHtmlListingSource(
        source_code="COTTON_UNIVERSITY",
        authority_code="COTTON_UNIVERSITY",
        authority_name="Cotton University",
        authority_type=AuthorityType.UNIVERSITY,
        listing_url="https://recruit.cottonuniversity.ac.in/",
        adapter_key="custom_html_listing_cotton_university",
        organization_name="Cotton University",
        priority=76,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=(
            "recruit.cottonuniversity.ac.in",
            "cottonuniversity.ac.in",
            "www.cottonuniversity.ac.in",
        ),
        detail_path_prefixes=("/advertisement/", "/recruitment/", "/notice/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
    "ASTU_ASSAM": CustomHtmlListingSource(
        source_code="ASTU_ASSAM",
        authority_code="ASTU_ASSAM",
        authority_name="Assam Science and Technology University",
        authority_type=AuthorityType.UNIVERSITY,
        listing_url="https://astu.ac.in/?page_id=110",
        adapter_key="custom_html_listing_astu",
        organization_name="Assam Science and Technology University",
        priority=78,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("astu.ac.in", "www.astu.ac.in"),
        detail_path_prefixes=("/career/", "/recruitment/", "/notice/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
}

# Activation remains evidence-driven after deterministic tests and one bounded live validation.
CUSTOM_HTML_SOURCES: dict[str, CustomHtmlListingSource] = {
    code: CUSTOM_HTML_SOURCE_CANDIDATES[code]
    for code in ("APGCL_ASSAM", "AEGCL_ASSAM")
}
