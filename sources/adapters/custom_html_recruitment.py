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
}

# Activation remains evidence-driven after deterministic tests and one bounded live validation.
CUSTOM_HTML_SOURCES: dict[str, CustomHtmlListingSource] = {
    code: CUSTOM_HTML_SOURCE_CANDIDATES[code]
    for code in ("APGCL_ASSAM", "AEGCL_ASSAM")
}
