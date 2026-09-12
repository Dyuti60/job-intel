import re
from dataclasses import dataclass

from app.core.config import Settings
from app.models.confidence import FieldCriticality

POLICY_VERSION = "V1"

CRITICAL_EXACT_PATHS = frozenset(
    {
        "application.start_date",
        "application.end_date",
        "application.deadline",
        "application.last_date",
        "application.url",
        "application.apply_url",
        "eligibility.minimum_age",
        "eligibility.maximum_age",
        "eligibility.age_cutoff_date",
        "vacancies.total",
    }
)
CRITICAL_PREFIXES = (
    "eligibility.age_relaxation",
    "eligibility.qualification",
    "eligibility.domicile",
    "eligibility.experience",
    "qualification.",
    "domicile.",
    "experience.",
)
CRITICAL_POST_PATTERN = re.compile(
    r"^posts\.\d+\.(?:vacancies(?:\.|$)|eligibility(?:\.|$)|"
    r"qualification(?:\.|$)|experience(?:\.|$)|age(?:\.|$))"
)


@dataclass(frozen=True)
class ConfidencePolicyV1:
    standard_threshold: int = 80
    critical_threshold: int = 90
    revision_threshold: int = 85

    @classmethod
    def from_settings(cls, settings: Settings) -> "ConfidencePolicyV1":
        return cls(
            standard_threshold=settings.confidence_standard_threshold,
            critical_threshold=settings.confidence_critical_threshold,
            revision_threshold=settings.confidence_revision_threshold,
        )

    def as_dict(self) -> dict[str, int | str]:
        return {
            "policy_version": POLICY_VERSION,
            "standard_threshold": self.standard_threshold,
            "critical_threshold": self.critical_threshold,
            "revision_threshold": self.revision_threshold,
        }


def classify_field_criticality(field_path: str) -> FieldCriticality:
    if (
        field_path in CRITICAL_EXACT_PATHS
        or any(field_path.startswith(prefix) for prefix in CRITICAL_PREFIXES)
        or CRITICAL_POST_PATTERN.match(field_path) is not None
    ):
        return FieldCriticality.CRITICAL
    return FieldCriticality.STANDARD
