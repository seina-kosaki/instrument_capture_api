from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message: str, details: object | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(DomainError):
    code = "not_found"


class Conflict(DomainError):
    code = "conflict"


class InvalidInput(DomainError):
    code = "invalid_input"


class TagValidationFailed(DomainError):
    code = "tag_validation_failed"
