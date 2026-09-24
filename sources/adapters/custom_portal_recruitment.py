from dataclasses import dataclass

from app.models.source_registry import AuthorityType
from sources.adapters.dated_document_resolver import (
    DatedDocumentResolverAdapter,
    DatedDocumentSource,
)


@dataclass(frozen=True)
class CustomPortalSource(DatedDocumentSource):
    """Configuration for a bounded authority-owned recruitment portal/index."""


class CustomPortalAdapter(DatedDocumentResolverAdapter):
    """Resolve portal advertisements through the shared bounded document pipeline."""


_PORTAL_ACTION_TERMS = (
    "application form",
    "apply online",
    "login",
    "register",
    "registration",
)


CUSTOM_PORTAL_SOURCE_CANDIDATES = {
    "AMTRON_ASSAM": CustomPortalSource(
        source_code="AMTRON_ASSAM",
        authority_code="AMTRON_ASSAM",
        authority_name="Assam Electronics Development Corporation Limited",
        authority_type=AuthorityType.PSU,
        listing_url="https://recruitment.amtron.in/",
        adapter_key="custom_portal_amtron",
        organization_name="Assam Electronics Development Corporation Limited",
        priority=69,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("recruitment.amtron.in", "amtron.in", "www.amtron.in"),
        detail_path_prefixes=(
            "/advertisement/",
            "/recruitment/",
            "/documents/",
            "/career/",
            "/jobs/",
        ),
        excluded_link_terms=_PORTAL_ACTION_TERMS,
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
    "AAU_ASSAM": CustomPortalSource(
        source_code="AAU_ASSAM",
        authority_code="AAU_ASSAM",
        authority_name="Assam Agricultural University",
        authority_type=AuthorityType.UNIVERSITY,
        listing_url="https://www.appl.aau.ac.in/recuitments/index.php",
        adapter_key="custom_portal_aau",
        organization_name="Assam Agricultural University",
        priority=77,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=(
            "www.appl.aau.ac.in",
            "appl.aau.ac.in",
            "www.aau.ac.in",
            "aau.ac.in",
        ),
        detail_path_prefixes=(
            "/recuitments/",
            "/recruitments/",
            "/advertisement/",
            "/documents/",
        ),
        excluded_link_terms=_PORTAL_ACTION_TERMS,
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
    ),
}

# Activation remains evidence-driven after deterministic tests and one bounded live validation.
CUSTOM_PORTAL_SOURCES: dict[str, CustomPortalSource] = {}
