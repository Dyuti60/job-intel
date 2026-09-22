import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.models.candidates import CandidateField, CandidateValueType
from app.models.evidence import Evidence
from app.models.verification import EvidenceAssessmentType


@dataclass(frozen=True)
class EvidenceInterpretation:
    assessment: EvidenceAssessmentType
    asserted_value: Any = None
    asserted_value_type: CandidateValueType | None = None
    note: str = "Evidence retained as context; no unambiguous typed assertion was found."


class CandidateFieldEvidenceVerifier:
    """Conservatively interpret persisted extraction evidence without network or AI."""

    _INTEGER_PATTERNS = {
        "vacancies.total": (
            r"(?:no\.?\s*of\s*posts?|number\s+of\s+posts?|vacanc(?:y|ies)|total\s+posts?)"
            r"\s*[:=\-]{0,2}\s*0*(\d+)\b",
        ),
        "eligibility.minimum_age": (
            r"(?:not\s+(?:be\s+)?less\s+than|minimum\s+age)"
            r"\s*[:=\-]?\s*(\d+)\s*years?\b",
        ),
        "age.minimum": (
            r"(?:not\s+(?:be\s+)?less\s+than|minimum\s+age)"
            r"\s*[:=\-]?\s*(\d+)\s*years?\b",
        ),
        "eligibility.maximum_age": (
            r"(?:not\s+(?:be\s+)?more\s+than|maximum\s+age)"
            r"\s*[:=\-]?\s*(\d+)\s*years?\b",
        ),
        "age.maximum": (
            r"(?:not\s+(?:be\s+)?more\s+than|maximum\s+age)"
            r"\s*[:=\-]?\s*(\d+)\s*years?\b",
        ),
    }
    _DATE_LABELS = {
        "application.start_date": (
            "starting date for online application",
            "application start date",
            "start date",
        ),
        "application.end_date": (
            "closing date for online application",
            "application end date",
            "last date",
            "end date",
        ),
        "eligibility.age_cutoff_date": ("age cutoff date", "reckoned as on", "as on"),
        "notification.date": ("notification date", "dated", "guwahati the"),
    }
    _DATE_TOKEN = r"(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2})"

    def evaluate(self, field: CandidateField, evidence: Evidence) -> EvidenceInterpretation:
        text = self._comparison_text(evidence)
        if field.value_type == CandidateValueType.STRING:
            return self._string(field.value, text)
        if field.value_type == CandidateValueType.INTEGER:
            return self._integer(field.field_path, field.value, text)
        if field.value_type == CandidateValueType.DATE:
            return self._date(field.field_path, field.value, text)
        return EvidenceInterpretation(EvidenceAssessmentType.CONTEXT_ONLY)

    @classmethod
    def _integer(cls, field_path: str, expected: Any, text: str) -> EvidenceInterpretation:
        if field_path == "vacancies.total":
            post_counts = [
                int(match.group(1).replace(",", ""))
                for match in re.finditer(r"\b([0-9][0-9,]*)\s+posts?\b", text, re.I)
            ]
            if post_counts and sum(post_counts) == int(expected):
                return EvidenceInterpretation(
                    EvidenceAssessmentType.SUPPORTS,
                    int(expected),
                    CandidateValueType.INTEGER,
                    "Candidate total equals the deterministic sum of labelled post counts.",
                )
            if len(post_counts) > 1:
                return EvidenceInterpretation(EvidenceAssessmentType.CONTEXT_ONLY)
        patterns = cls._INTEGER_PATTERNS.get(field_path, ())
        values = {
            int(match.group(1))
            for pattern in patterns
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        }
        return cls._typed_result(values, int(expected), CandidateValueType.INTEGER)

    @classmethod
    def _date(cls, field_path: str, expected: Any, text: str) -> EvidenceInterpretation:
        labels = cls._DATE_LABELS.get(field_path, ())
        for label in labels:
            values: set[str] = set()
            pattern = rf"{re.escape(label)}[^\n]{{0,100}}?{cls._DATE_TOKEN}"
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                parsed = cls._parse_date(match.group(1))
                if parsed is not None:
                    values.add(parsed)
            if values:
                return cls._typed_result(values, str(expected), CandidateValueType.DATE)
        return EvidenceInterpretation(EvidenceAssessmentType.CONTEXT_ONLY)

    @staticmethod
    def _string(expected: Any, text: str) -> EvidenceInterpretation:
        normalized = CandidateFieldEvidenceVerifier._normalize_text(str(expected))
        if normalized and normalized in text:
            return EvidenceInterpretation(
                EvidenceAssessmentType.SUPPORTS,
                expected,
                CandidateValueType.STRING,
                "Normalized candidate string is explicitly present in persisted evidence.",
            )
        return EvidenceInterpretation(EvidenceAssessmentType.CONTEXT_ONLY)

    @staticmethod
    def _typed_result(
        values: set[Any], expected: Any, value_type: CandidateValueType
    ) -> EvidenceInterpretation:
        if len(values) != 1:
            return EvidenceInterpretation(EvidenceAssessmentType.CONTEXT_ONLY)
        asserted = next(iter(values))
        assessment = (
            EvidenceAssessmentType.SUPPORTS
            if asserted == expected
            else EvidenceAssessmentType.CONTRADICTS
        )
        return EvidenceInterpretation(
            assessment,
            asserted,
            value_type,
            "A single field-labelled typed value was deterministically extracted from evidence.",
        )

    @classmethod
    def _comparison_text(cls, evidence: Evidence) -> str:
        parts = [evidence.excerpt]
        if evidence.context:
            parts.append(evidence.context)
        return cls._normalize_text("\n".join(parts))

    @staticmethod
    def _normalize_text(value: str) -> str:
        value = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
        return re.sub(r"\s+", " ", value).strip().casefold()

    @staticmethod
    def _parse_date(value: str) -> str | None:
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return date.fromisoformat(value).isoformat()
            day, month, year = re.split(r"[/-]", value)
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None
