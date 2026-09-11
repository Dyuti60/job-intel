class DomainError(Exception):
    """Base class for expected domain failures."""


class ResourceNotFoundError(DomainError):
    """A requested registry resource does not exist."""


class DuplicateResourceError(DomainError):
    """A registry uniqueness rule would be violated."""
