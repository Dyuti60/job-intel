import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pypdf import PdfReader

from app.models.candidates import CandidateValueType
from app.models.discovery import DocumentType
from sources.http import BoundedHttpClient, FetchedResource

APSC_PORTAL_URL = "https://apscrecruitment.in/"
APSC_FEED_URL = "https://apscrecruitment.in/server/api/Advertisement/WhatsNew"
APSC_ADVERTISEMENT_URL = "https://apsc.nic.in/advt_2026/Advt_no_12-2026_website.pdf"
TARGET_ADVERTISEMENT = "12/2026"
TARGET_TITLE = "Research Assistant under Labour Welfare Department"


@dataclass(frozen=True)
class ParsedField:
    field_path: str
    value_type: CandidateValueType
    value: Any
    raw_value: str
    source_locator: str
    excerpt: str
    context: str | None = None


@dataclass(frozen=True)
class AdapterDocument:
    resource: FetchedResource
    document_type: DocumentType
    extension: str


@dataclass(frozen=True)
class AdapterResult:
    documents: tuple[AdapterDocument, ...]
    extraction_document_index: int
    fields: tuple[ParsedField, ...]
    warnings: tuple[str, ...]


def candidate_key(advertisement_number: str) -> str:
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d{4})\s*", advertisement_number)
    if not match:
        raise ValueError("Unsupported APSC advertisement number")
    return f"APSC_ADVT_{int(match.group(1))}_{match.group(2)}"


class APSCRecruitmentAdapter:
    """Narrow deterministic adapter for APSC Advertisement 12/2026 only."""

    def __init__(self, http: BoundedHttpClient) -> None:
        self.http = http

    def discover(self) -> AdapterResult:
        portal = self.http.fetch(APSC_PORTAL_URL, accepted_types=("text/html",))
        feed = self.http.fetch(APSC_FEED_URL, accepted_types=("application/json",))
        documents = [
            AdapterDocument(portal, DocumentType.HTML, "html"),
            AdapterDocument(feed, DocumentType.JSON, "json"),
        ]
        portal_fields = parse_portal_feed(feed.content)
        warnings: list[str] = []
        try:
            advertisement = self.http.fetch(
                APSC_ADVERTISEMENT_URL, accepted_types=("application/pdf",)
            )
            documents.append(AdapterDocument(advertisement, DocumentType.PDF, "pdf"))
            pdf_fields = parse_advertisement_pdf(advertisement.content)
            fields = pdf_fields or portal_fields
            extraction_index = 2 if pdf_fields else 1
            if not pdf_fields:
                warnings.append("Official PDF contained no supported extractable fields")
        except Exception as error:
            if not portal_fields:
                raise
            fields = portal_fields
            extraction_index = 1
            warnings.append(f"Official advertisement unavailable: {type(error).__name__}: {error}")
        if not fields:
            raise ValueError("APSC Advertisement 12/2026 was not found in official source content")
        return AdapterResult(tuple(documents), extraction_index, tuple(fields), tuple(warnings))


def parse_portal_feed(content: bytes) -> list[ParsedField]:
    payload = json.loads(content.decode("utf-8-sig"))
    rows = payload.get("result", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    for row in rows:
        flattened = " ".join(_string_values(row))
        if TARGET_TITLE.lower() not in flattened.lower() or not re.search(
            r"12\s*/\s*2026", flattened
        ):
            continue
        deadline = re.search(r"(?:end\s*date\s*:?\s*)?(\d{2}/\d{2}/\d{4})", flattened, re.I)
        excerpt = flattened[:4000]
        result = _identity_fields(excerpt, "portal:whats-new:advt-12-2026")
        if deadline:
            result.append(
                ParsedField(
                    "application.end_date",
                    CandidateValueType.DATE,
                    datetime.strptime(deadline.group(1), "%d/%m/%Y").date().isoformat(),
                    deadline.group(1),
                    "portal:whats-new:advt-12-2026",
                    excerpt,
                )
            )
        return result
    return []


def parse_advertisement_pdf(content: bytes) -> list[ParsedField]:
    reader = PdfReader(io.BytesIO(content))
    pages = [(page.extract_text() or "")[:100_000] for page in reader.pages[:40]]
    return parse_advertisement_text("\n".join(pages))


def parse_advertisement_text(text: str) -> list[ParsedField]:
    """Parse bounded text extracted from the supported official advertisement layout."""
    compact = re.sub(r"[ \t]+", " ", text)
    if not re.search(r"(?:Advertisement|ADVT).*?12\s*/\s*2026", compact, re.I | re.S):
        return []
    fields = _identity_fields(
        _excerpt(compact, r"Research Assistant.{0,240}"), "pdf:page=1;advt=12/2026"
    )
    patterns: list[tuple[str, CandidateValueType, str, Any]] = [
        (
            "notification.date",
            CandidateValueType.DATE,
            r"(?:dated|Guwahati,? the)\s+(?:the\s+)?(\d{1,2}(?:st|nd|rd|th)?\s+\w+[, ]+2026)",
            _date_words,
        ),
        (
            "vacancies.total",
            CandidateValueType.INTEGER,
            r"(?:No\.?\s*of\s*posts?|number\s+of\s+posts?).{0,80}?\b(\d+)\b",
            int,
        ),
        (
            "application.start_date",
            CandidateValueType.DATE,
            r"(?:STARTING DATE|online applications? opens?|start date).{0,80}?"
            r"(\d{2}[./-]\d{2}[./-]\d{4})",
            _date_numeric,
        ),
        (
            "application.end_date",
            CandidateValueType.DATE,
            r"(?:CLOSING DATE|last date|end date).{0,100}?(\d{2}[./-]\d{2}[./-]\d{4})",
            _date_numeric,
        ),
        (
            "eligibility.minimum_age",
            CandidateValueType.INTEGER,
            r"(?:not be less than|minimum age).{0,30}?(\d{2})\s*years",
            int,
        ),
        (
            "eligibility.maximum_age",
            CandidateValueType.INTEGER,
            r"(?:not be more than|maximum age).{0,30}?(\d{2})\s*years",
            int,
        ),
        (
            "eligibility.age_cutoff_date",
            CandidateValueType.DATE,
            r"(?:as on|reckoned as on)\s*(\d{2}[./-]\d{2}[./-]\d{4})",
            _date_numeric,
        ),
    ]
    for path, value_type, pattern, converter in patterns:
        match = re.search(pattern, compact, re.I | re.S)
        if match:
            excerpt = _excerpt(compact, pattern)
            fields.append(
                ParsedField(
                    path,
                    value_type,
                    converter(match.group(1)),
                    match.group(1),
                    f"pdf:label={path}",
                    excerpt,
                )
            )
    for path, pattern in (
        (
            "eligibility.qualification.summary",
            r"(?:EDUCATIONAL QUALIFICATION|Minimum qualification).{0,700}",
        ),
        ("eligibility.domicile.summary", r"(?:permanent resident of Assam|domicile).{0,500}"),
        ("pay.scale", r"(?:Scale of Pay|Pay scale).{0,240}"),
    ):
        match = re.search(pattern, compact, re.I | re.S)
        if match:
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            fields.append(
                ParsedField(
                    path, CandidateValueType.STRING, value, value, f"pdf:label={path}", value
                )
            )
    unique = {field.field_path: field for field in fields}
    return [unique[path] for path in sorted(unique)]


def _identity_fields(excerpt: str, locator: str) -> list[ParsedField]:
    return [
        ParsedField(
            "recruitment_name",
            CandidateValueType.STRING,
            TARGET_TITLE,
            TARGET_TITLE,
            locator,
            excerpt,
        ),
        ParsedField(
            "organization.name",
            CandidateValueType.STRING,
            "Assam Public Service Commission",
            "Assam Public Service Commission",
            locator,
            excerpt,
        ),
        ParsedField(
            "department.name",
            CandidateValueType.STRING,
            "Labour Welfare Department",
            "Labour Welfare Department",
            locator,
            excerpt,
        ),
        ParsedField(
            "notification.number",
            CandidateValueType.STRING,
            TARGET_ADVERTISEMENT,
            TARGET_ADVERTISEMENT,
            locator,
            excerpt,
        ),
        ParsedField(
            "post.name",
            CandidateValueType.STRING,
            "Research Assistant",
            "Research Assistant",
            locator,
            excerpt,
        ),
        ParsedField(
            "application.mode", CandidateValueType.STRING, "ONLINE", "online", locator, excerpt
        ),
    ]


def _string_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _string_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _string_values(nested)]
    return [str(value)] if value is not None else []


def _date_numeric(value: str) -> str:
    return (
        datetime.strptime(value.replace(".", "/").replace("-", "/"), "%d/%m/%Y").date().isoformat()
    )


def _date_words(value: str) -> str:
    clean = re.sub(r"(\d)(?:st|nd|rd|th)", r"\1", value, flags=re.I).replace(",", "")
    return datetime.strptime(re.sub(r"\s+", " ", clean.strip()), "%d %B %Y").date().isoformat()


def _excerpt(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return text[:1000].strip()
    start = max(0, match.start() - 120)
    return re.sub(r"\s+", " ", text[start : min(len(text), match.end() + 120)]).strip()[:4000]
