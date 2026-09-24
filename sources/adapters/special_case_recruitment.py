import hashlib
import re
from dataclasses import dataclass

from app.models.source_registry import AuthorityType, SourceScheduleGroup
from sources.adapters.dated_document_resolver import (
    DatedDocumentResolverAdapter,
    DatedDocumentSource,
    DocumentListingItem,
)
from sources.adapters.official_recruitment_archive import ArchiveNoticeMetadata
from sources.extraction import ParsedAdvertisement


@dataclass(frozen=True)
class SpecialCaseSource(DatedDocumentSource):
    safety_rule: str = ""


class SpecialCaseRecruitmentAdapter(DatedDocumentResolverAdapter):
    """Apply narrowly configured ownership/identity safeguards before shared persistence."""

    def accepts_item(self, item: DocumentListingItem) -> bool:
        if self.source.safety_rule == "GHC_ASSAM_JURISDICTION":
            return _is_assam_principal_seat_notice(item.title)
        if self.source.safety_rule == "SLRC_CAMPAIGN_IDENTITY":
            return _is_slrc_campaign_notice(item.title)
        return False

    def candidate_key(
        self,
        metadata: ArchiveNoticeMetadata,
        extraction: ParsedAdvertisement,
    ) -> str | None:
        if self.source.safety_rule != "SLRC_CAMPAIGN_IDENTITY":
            return super().candidate_key(metadata, extraction)
        reference = next(
            (
                str(field.value)
                for field in extraction.fields
                if field.field_path == "notification.number" and field.value
            ),
            None,
        )
        year_match = re.search(r"\b(20\d{2})\b", metadata.title)
        if reference is None or year_match is None:
            return None
        normalized_reference = re.sub(r"[^A-Z0-9]+", "-", reference.upper()).strip("-")
        identity = f"SLRC_ASSAM|{year_match.group(1)}|{normalized_reference}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12].upper()
        return f"SLRC_ASSAM_ADVT_{year_match.group(1)}_{digest}"


def _is_assam_principal_seat_notice(title: str) -> bool:
    normalized = title.casefold()
    other_jurisdictions = (
        "aizawl bench",
        "itanagar bench",
        "kohima bench",
        "arunachal pradesh",
        "mizoram",
        "nagaland",
    )
    if any(marker in normalized for marker in other_jurisdictions):
        return False
    return "principal seat" in normalized or bool(re.search(r"\bassam\b", normalized))


def _is_slrc_campaign_notice(title: str) -> bool:
    normalized = title.casefold()
    return "adre" in normalized or "state level recruitment commission" in normalized


SPECIAL_CASE_SOURCE_CANDIDATES = {
    "GHC_ASSAM": SpecialCaseSource(
        source_code="GHC_ASSAM",
        authority_code="GHC_ASSAM",
        authority_name="Gauhati High Court",
        authority_type=AuthorityType.OTHER,
        listing_url="https://ghconline.gov.in/index.php/recruitment-notices/",
        adapter_key="special_case_ghc_assam",
        organization_name="Gauhati High Court, Principal Seat",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=52,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("ghconline.gov.in", "www.ghconline.gov.in"),
        detail_path_prefixes=("/index.php/recruitment-notices/", "/recruitment/"),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
        safety_rule="GHC_ASSAM_JURISDICTION",
    ),
    "SLRC_ASSAM": SpecialCaseSource(
        source_code="SLRC_ASSAM",
        authority_code="SLRC_ASSAM",
        authority_name="State Level Recruitment Commissions, Assam",
        authority_type=AuthorityType.COMMISSION,
        listing_url="https://site.sebaonline.org/",
        adapter_key="special_case_slrc_assam",
        organization_name="State Level Recruitment Commissions, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=25,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("site.sebaonline.org", "sebaonline.org", "www.sebaonline.org"),
        detail_path_prefixes=("/",),
        max_listing_rows_per_run=100,
        max_detail_pages_per_run=10,
        safety_rule="SLRC_CAMPAIGN_IDENTITY",
    ),
}

# Activation remains evidence-driven after deterministic tests and one bounded live validation.
SPECIAL_CASE_SOURCES: dict[str, SpecialCaseSource] = {}
