import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.discovery import DiscoveryRunStatus, DiscoveryTriggerType, ObservationStatus
from app.models.evidence import EvidenceType
from app.models.source_registry import (
    AuthorityStatus,
    AuthorityType,
    SourceClass,
    SourceScheduleGroup,
    SourceStatus,
    SourceType,
)
from app.repositories.candidates import RecruitmentCandidateRepository
from app.repositories.source_registry import RecruitingAuthorityRepository, SourceEndpointRepository
from app.schemas.candidates import (
    CandidateFieldCreate,
    RecruitmentCandidateCreate,
    RecruitmentCandidateRevisionCreate,
    RecruitmentPostCreate,
)
from app.schemas.discovery import DiscoveryRunComplete, DocumentObservationCreate
from app.schemas.evidence import EvidenceCreate
from app.schemas.source_registry import RecruitingAuthorityCreate, SourceEndpointCreate
from app.services.candidates import CandidateService
from app.services.discovery import DiscoveryService
from app.services.evidence import EvidenceService
from app.services.exceptions import DomainConflictError
from app.services.raw_storage import LocalRawStorage
from app.services.source_registry import SourceRegistryService
from app.services.url_normalization import normalize_http_url
from sources.adapters.apsc_recruitment import (
    APSC_PORTAL_URL,
    TARGET_ADVERTISEMENT,
    TARGET_TITLE,
    AdapterResult,
    APSCRecruitmentAdapter,
    candidate_key,
)
from sources.http import BoundedHttpClient


@dataclass
class DiscoverySummary:
    run_id: str
    status: str
    documents_new: int
    documents_changed: int
    documents_unchanged: int
    candidates_created: int
    candidates_reused: int
    revisions_created: int
    revisions_reused: int
    fields_extracted: int
    evidence_records: int
    warnings: tuple[str, ...]
    dry_run: bool
    source: str = "APSC"


class APSCDiscoveryWorkerService:
    def __init__(self, session: Session, settings: Settings, logger: logging.Logger) -> None:
        self.session = session
        self.settings = settings
        self.logger = logger

    def run(
        self, *, dry_run: bool = False, adapter: APSCRecruitmentAdapter | None = None
    ) -> DiscoverySummary:
        registry = SourceRegistryService(self.session, commit=False)
        authority, endpoint = self._ensure_registry(registry)
        discovery = DiscoveryService(self.session, commit=False)
        candidates = CandidateService(self.session, commit=False)
        evidence = EvidenceService(self.session, commit=False)
        run = discovery.create_run(endpoint.id, DiscoveryTriggerType.MANUAL)
        owns_http = adapter is None
        http = None
        try:
            if adapter is None:
                http = BoundedHttpClient(
                    connect_timeout=self.settings.discovery_connect_timeout_seconds,
                    read_timeout=self.settings.discovery_read_timeout_seconds,
                    retries=self.settings.discovery_http_retries,
                    max_response_bytes=self.settings.discovery_max_response_bytes,
                    requests_per_minute=6,
                )
                adapter = APSCRecruitmentAdapter(http)
            result = adapter.discover()
            summary = self._persist_result(
                authority.id,
                endpoint.id,
                run.id,
                result,
                discovery,
                candidates,
                evidence,
                dry_run=dry_run,
            )
            completion = "PARTIAL" if result.warnings else "SUCCEEDED"
            run = discovery.complete_run(
                run.id,
                DiscoveryRunComplete(
                    status=completion,
                    error_code="DETAIL_DOCUMENT_LIMITATION" if result.warnings else None,
                    error_message="; ".join(result.warnings)[:4000] if result.warnings else None,
                ),
            )
            summary.status = run.status.value
            summary.warnings = result.warnings
            summary.dry_run = dry_run
            if dry_run:
                self.session.rollback()
            else:
                self.session.commit()
            return summary
        except Exception:
            self.session.rollback()
            self.logger.exception("apsc_discovery_failed run_id=%s", run.id)
            raise
        finally:
            if owns_http and http is not None:
                http.close()

    def _ensure_registry(self, registry: SourceRegistryService):
        authorities = RecruitingAuthorityRepository(self.session)
        endpoints = SourceEndpointRepository(self.session)
        authority = authorities.get_by_code("APSC")
        if authority is None:
            authority = registry.create_authority(
                RecruitingAuthorityCreate(
                    code="APSC",
                    name="Assam Public Service Commission",
                    authority_type=AuthorityType.COMMISSION,
                    official_website_url=APSC_PORTAL_URL,
                    status=AuthorityStatus.ACTIVE,
                )
            )
        elif (
            authority.name != "Assam Public Service Commission"
            or authority.authority_type != AuthorityType.COMMISSION
            or authority.status != AuthorityStatus.ACTIVE
        ):
            raise DomainConflictError(
                "Existing APSC authority conflicts with adapter registry metadata"
            )

        endpoint = endpoints.get_by_canonical_url(normalize_http_url(APSC_PORTAL_URL))
        if endpoint is None:
            endpoint = registry.create_endpoint(
                SourceEndpointCreate(
                    recruiting_authority_id=authority.id,
                    name="APSC Online Recruitment Portal",
                    canonical_url=APSC_PORTAL_URL,
                    source_type=SourceType.APPLICATION_PORTAL,
                    source_class=SourceClass.AUTHORITATIVE_OFFICIAL,
                    status=SourceStatus.ACTIVE,
                    discovery_enabled=True,
                    adapter_key="apsc_recruitment",
                    schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
                    poll_interval_minutes=360,
                    priority=10,
                    requests_per_minute=6,
                    provenance_note="Official APSC online recruitment and application portal.",
                )
            )
        elif (
            endpoint.recruiting_authority_id != authority.id
            or endpoint.source_class != SourceClass.AUTHORITATIVE_OFFICIAL
            or endpoint.adapter_key != "apsc_recruitment"
            or endpoint.status != SourceStatus.ACTIVE
            or not endpoint.discovery_enabled
        ):
            raise DomainConflictError(
                "Existing APSC endpoint conflicts with adapter registry metadata"
            )
        return authority, endpoint

    def _persist_result(
        self,
        authority_id,
        endpoint_id,
        run_id,
        result: AdapterResult,
        discovery: DiscoveryService,
        candidates: CandidateService,
        evidence: EvidenceService,
        *,
        dry_run: bool,
    ) -> DiscoverySummary:
        storage = LocalRawStorage(self.settings.raw_storage_root)
        documents = []
        classifications: list[ObservationStatus] = []
        for item in result.documents:
            digest = hashlib.sha256(item.resource.content).hexdigest()
            stored_uri = f"raw://dry-run/{digest}.{item.extension}"
            if not dry_run:
                stored_uri = storage.store(
                    source_code="APSC",
                    content=item.resource.content,
                    extension=item.extension,
                    observed_at=item.resource.retrieved_at,
                ).storage_uri
            classification, document, _ = discovery.record_document(
                run_id,
                DocumentObservationCreate(
                    document_url=item.resource.url,
                    document_type=item.document_type,
                    content_type=item.resource.content_type,
                    content_hash=digest,
                    content_length=len(item.resource.content),
                    http_status_code=item.resource.status_code,
                    http_etag=item.resource.etag,
                    http_last_modified=item.resource.last_modified,
                    retrieved_at=item.resource.retrieved_at,
                    storage_uri=stored_uri,
                ),
            )
            classifications.append(classification)
            documents.append(document)
        source_document = documents[result.extraction_document_index]
        key = candidate_key(TARGET_ADVERTISEMENT)
        repository = RecruitmentCandidateRepository(self.session)
        candidate = repository.get_by_identity(authority_id, key)
        candidate_created = candidate is None
        if candidate is None:
            candidate = candidates.create_candidate(
                RecruitmentCandidateCreate(
                    recruiting_authority_id=authority_id,
                    candidate_key=key,
                    display_name=TARGET_TITLE,
                )
            )
        revision, revision_created = candidates.create_revision(
            candidate.id,
            RecruitmentCandidateRevisionCreate(
                source_document_id=source_document.id,
                extraction_method="APSC_ADVERTISEMENT_12_2026_V1",
                extraction_note=(
                    "Deterministic extraction from persisted official APSC source bytes."
                ),
                split_status=result.split_status,
                split_note=result.split_note,
                fields=[
                    CandidateFieldCreate(
                        field_path=field.field_path,
                        value_type=field.value_type,
                        value=field.value,
                        raw_value=field.raw_value,
                        source_locator=field.source_locator,
                    )
                    for field in result.fields
                ],
                posts=[
                    RecruitmentPostCreate(
                        post_key=post.post_key,
                        ordinal=post.ordinal,
                        name=post.name,
                        normalized_name=post.normalized_name,
                        source_locator=post.source_locator,
                        facts=[
                            CandidateFieldCreate(
                                field_path=fact.field_path,
                                value_type=fact.value_type,
                                value=fact.value,
                                raw_value=fact.raw_value,
                                source_locator=fact.source_locator,
                            )
                            for fact in post.facts
                        ],
                    )
                    for post in result.posts
                ],
            ),
        )
        evidence_ids = set()
        parsed_by_path = {field.field_path: field for field in result.fields}
        parsed_by_path.update(
            {
                f"posts.{post.post_key}.{fact.field_path}": fact
                for post in result.posts
                for fact in post.facts
            }
        )
        for field_model in revision.fields:
            parsed = parsed_by_path[field_model.field_path]
            evidence_model, _ = evidence.create_evidence(
                EvidenceCreate(
                    source_document_id=source_document.id,
                    evidence_type=EvidenceType.TEXT_EXCERPT,
                    source_locator=parsed.source_locator,
                    excerpt=parsed.excerpt[:8000],
                    context=parsed.context,
                )
            )
            evidence.link_evidence(field_model.id, evidence_model.id)
            evidence_ids.add(evidence_model.id)
        return DiscoverySummary(
            run_id=str(run_id),
            status=DiscoveryRunStatus.RUNNING.value,
            documents_new=classifications.count(ObservationStatus.NEW),
            documents_changed=classifications.count(ObservationStatus.CHANGED),
            documents_unchanged=classifications.count(ObservationStatus.UNCHANGED),
            candidates_created=int(candidate_created),
            candidates_reused=int(not candidate_created),
            revisions_created=int(revision_created),
            revisions_reused=int(not revision_created),
            fields_extracted=len(parsed_by_path),
            evidence_records=len(evidence_ids),
            warnings=(),
            dry_run=False,
        )


def format_discovery_summary(summary: DiscoverySummary) -> str:
    mode = "DRY RUN — NO DATABASE CHANGES" if summary.dry_run else "PERSISTED"
    warnings = "\n".join(f"  - {warning}" for warning in summary.warnings) or "  None"
    return f"""================================================
 Assam Job Intelligence — Discovery
 Source: {summary.source} ({mode})
================================================
Discovery Run: {summary.run_id}

Source documents:
  New:        {summary.documents_new}
  Changed:    {summary.documents_changed}
  Unchanged:  {summary.documents_unchanged}

Recruitments:
  Candidates created: {summary.candidates_created}
  Candidates reused:  {summary.candidates_reused}
  Revisions created:  {summary.revisions_created}
  Revisions reused:   {summary.revisions_reused}

Fields extracted:     {summary.fields_extracted}
Evidence records:     {summary.evidence_records}
Verification started: NO
Warnings:
{warnings}

Status: {summary.status}
================================================"""
