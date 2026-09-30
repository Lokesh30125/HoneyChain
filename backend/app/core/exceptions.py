"""HoneyChain API — domain exceptions and the canonical error codes.

Routes and services raise these; ``app.main`` maps them onto the standard error
envelope::

    {"success": false, "error": {"code": "NOT_FOUND", "message": "..."}}

Keeping the codes in one enum guarantees the frontend can switch on a stable,
documented vocabulary (see ``docs/api.md``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    DUPLICATE_RESOURCE = "DUPLICATE_RESOURCE"
    RATE_LIMITED = "RATE_LIMITED"
    BAD_REQUEST = "BAD_REQUEST"
    DATABASE_ERROR = "DATABASE_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class AppError(Exception):
    """Base class for every expected, client-safe application error."""

    status_code: int = 400
    code: ErrorCode = ErrorCode.BAD_REQUEST
    message: str = "Request could not be processed"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        details: list[dict[str, Any]] | dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)

    def to_error_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": str(self.code), "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class BadRequestError(AppError):
    status_code = 400
    code = ErrorCode.BAD_REQUEST
    message = "Invalid request"


class ValidationError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_ERROR
    message = "Request validation failed"


class AuthenticationError(AppError):
    status_code = 401
    code = ErrorCode.AUTHENTICATION_ERROR
    message = "Authentication required"


class InvalidCredentialsError(AppError):
    status_code = 401
    code = ErrorCode.INVALID_CREDENTIALS
    message = "Invalid email or password"


class TokenExpiredError(AppError):
    status_code = 401
    code = ErrorCode.TOKEN_EXPIRED
    message = "Session expired, please sign in again"


class TokenInvalidError(AppError):
    status_code = 401
    code = ErrorCode.TOKEN_INVALID
    message = "Invalid or revoked token"


class ForbiddenError(AppError):
    status_code = 403
    code = ErrorCode.PERMISSION_DENIED
    message = "You do not have permission to perform this action"


class InactiveAccountError(AppError):
    status_code = 403
    code = ErrorCode.ACCOUNT_INACTIVE
    message = "This account is inactive. Please contact an administrator"


class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = ErrorCode.CONFLICT
    message = "Resource conflict"


class DuplicateResourceError(ConflictError):
    code = ErrorCode.DUPLICATE_RESOURCE
    message = "Resource already exists"


class DatabaseError(AppError):
    status_code = 500
    code = ErrorCode.DATABASE_ERROR
    message = "A database error occurred"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = ErrorCode.SERVICE_UNAVAILABLE
    message = "Service temporarily unavailable"


class NotImplementedFeatureError(AppError):
    status_code = 501
    code = ErrorCode.NOT_IMPLEMENTED
    message = "This feature is not implemented yet"
