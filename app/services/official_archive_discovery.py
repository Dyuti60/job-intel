import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.discovery import DiscoveryRunStatus, DiscoveryTriggerType, ObservationStatus
from app.models.evidence import EvidenceType
from app.models.source_registry import AuthorityStatus, SourceClass, SourceStatus, SourceType
from app.repositories.candidates import RecruitmentCandidateRepository
from app.repositories.source_registry import RecruitingAuthorityRepository, SourceEndpointRepository
from app.schemas.candidates import (
    CandidateFieldCreate,
    RecruitmentCandidateCreate,
    RecruitmentCandidateRevisionCreate,
)
from app.schemas.discovery import DiscoveryRunComplete, DocumentObservationCreate
from app.schemas.evidence import EvidenceCreate
from app.schemas.source_registry import RecruitingAuthorityCreate, SourceEndpointCreate
from app.services.apsc_discovery import DiscoverySummary
from app.services.candidates import CandidateService
from app.services.discovery import DiscoveryService
from app.services.evidence import EvidenceService
from app.services.exceptions import DomainConflictError
from app.services.raw_storage import LocalRawStorage
from app.services.source_registry import SourceRegistryService
from app.services.url_normalization import normalize_http_url
from sources.adapters.official_recruitment_archive import (
    ArchiveAdapterResult,
    OfficialArchiveSource,
    OfficialRecruitmentArchiveAdapter,
)
from sources.http import BoundedHttpClient


class OfficialArchiveDiscoveryWorkerService:
    """Persist one bounded official recruitment archive through existing trust domains."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        logger: logging.Logger,
        source: OfficialArchiveSource,
    ) -> None:
        self.session = session
        self.settings = settings
        self.logger = logger
        self.source = source

    def run(
        self,
        *,
        dry_run: bool = False,
        adapter: OfficialRecruitmentArchiveAdapter | None = None,
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
                )
                adapter = OfficialRecruitmentArchiveAdapter(
                    http,
                    self.source,
                    earliest_year=datetime.now(UTC).year - 2,
                )
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
            completed = discovery.complete_run(
                run.id,
                DiscoveryRunComplete(
                    status=completion,
                    error_code="ARCHIVE_DOCUMENT_LIMITATION" if result.warnings else None,
                    error_message="; ".join(result.warnings)[:4000] if result.warnings else None,
                ),
            )
            summary.status = completed.status.value
            summary.warnings = result.warnings
            summary.dry_run = dry_run
            if dry_run:
                self.session.rollback()
            else:
                self.session.commit()
            return summary
        except Exception:
            self.session.rollback()
            self.logger.exception(
                "official_archive_discovery_failed source=%s run_id=%s",
                self.source.source_code,
                run.id,
            )
            raise
        finally:
            if owns_http and http is not None:
                http.close()

    def _ensure_registry(self, registry: SourceRegistryService):
        authorities = RecruitingAuthorityRepository(self.session)
        endpoints = SourceEndpointRepository(self.session)
        authority = authorities.get_by_code(self.source.authority_code)
        if authority is None:
            authority = registry.create_authority(
                RecruitingAuthorityCreate(
                    code=self.source.authority_code,
                    name=self.source.authority_name,
                    authority_type=self.source.authority_type,
                    official_website_url=self.source.listing_url,
                    status=AuthorityStatus.ACTIVE,
                )
            )
        elif (
            authority.name != self.source.authority_name
            or authority.authority_type != self.source.authority_type
            or authority.status != AuthorityStatus.ACTIVE
        ):
            raise DomainConflictError(
                f"Existing {self.source.authority_code} authority conflicts with adapter metadata"
            )

        endpoint = endpoints.get_by_canonical_url(normalize_http_url(self.source.listing_url))
        if endpoint is None:
            endpoint = registry.create_endpoint(
                SourceEndpointCreate(
                    recruiting_authority_id=authority.id,
                    name=f"{self.source.authority_name} Recruitment Archive",
                    canonical_url=self.source.listing_url,
                    source_type=SourceType.DOCUMENT_LISTING,
                    source_class=SourceClass.AUTHORITATIVE_OFFICIAL,
                    status=SourceStatus.ACTIVE,
                    discovery_enabled=True,
                    adapter_key=self.source.adapter_key,
                    provenance_note=(
                        "Official recruiting-authority advertisement archive; "
                        "bounded to dated 2024-2026 recruitment advertisements."
                    ),
                )
            )
        elif (
            endpoint.recruiting_authority_id != authority.id
            or endpoint.source_class != SourceClass.AUTHORITATIVE_OFFICIAL
            or endpoint.adapter_key != self.source.adapter_key
            or endpoint.status != SourceStatus.ACTIVE
            or not endpoint.discovery_enabled
        ):
            raise DomainConflictError(
                f"Existing {self.source.authority_code} endpoint conflicts with adapter metadata"
            )
        return authority, endpoint

    def _persist_result(
        self,
        authority_id,
        endpoint_id,
        run_id,
        result: ArchiveAdapterResult,
        discovery: DiscoveryService,
        candidates: CandidateService,
        evidence: EvidenceService,
        *,
        dry_run: bool,
    ) -> DiscoverySummary:
        storage = LocalRawStorage(self.settings.raw_storage_root)
        all_documents = [result.listing_document] + [notice.document for notice in result.notices]
        classifications: list[ObservationStatus] = []
        persisted_documents = []
        for item in all_documents:
            digest = hashlib.sha256(item.resource.content).hexdigest()
            stored_uri = f"raw://dry-run/{digest}.{item.extension}"
            if not dry_run:
                stored_uri = storage.store(
                    source_code=self.source.source_code,
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
            persisted_documents.append(document)

        repository = RecruitmentCandidateRepository(self.session)
        candidates_created = 0
        candidates_reused = 0
        revisions_created = 0
        revisions_reused = 0
        fields_extracted = 0
        evidence_ids = set()
        for notice, source_document in zip(
            result.notices, persisted_documents[1:], strict=True
        ):
            if not notice.fields:
                continue
            candidate = repository.get_by_identity(authority_id, notice.candidate_key)
            if candidate is None:
                candidate = candidates.create_candidate(
                    RecruitmentCandidateCreate(
                        recruiting_authority_id=authority_id,
                        candidate_key=notice.candidate_key,
                        display_name=notice.metadata.title,
                    )
                )
                candidates_created += 1
            else:
                candidates_reused += 1
            revision, created = candidates.create_revision(
                candidate.id,
                RecruitmentCandidateRevisionCreate(
                    source_document_id=source_document.id,
                    extraction_method=f"{self.source.adapter_key.upper()}_V1",
                    extraction_note=(
                        "Conservative deterministic extraction from a persisted official "
                        "recruitment advertisement."
                    ),
                    fields=[
                        CandidateFieldCreate(
                            field_path=field.field_path,
                            value_type=field.value_type,
                            value=field.value,
                            raw_value=field.raw_value,
                            source_locator=field.source_locator,
                        )
                        for field in notice.fields
                    ],
                ),
            )
            revisions_created += int(created)
            revisions_reused += int(not created)
            fields_extracted += len(notice.fields)
            for field_model, parsed in zip(
                revision.fields,
                sorted(notice.fields, key=lambda field: field.field_path),
                strict=True,
            ):
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
            candidates_created=candidates_created,
            candidates_reused=candidates_reused,
            revisions_created=revisions_created,
            revisions_reused=revisions_reused,
            fields_extracted=fields_extracted,
            evidence_records=len(evidence_ids),
            warnings=(),
            dry_run=False,
            source=self.source.source_code,
        )
