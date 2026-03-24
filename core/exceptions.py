"""
Custom exceptions for the review system.
"""


class ReviewSystemError(Exception):
    """Base class for exceptions in this package."""

    pass


class GerritAPIError(ReviewSystemError):
    """Raised when communication with Gerrit fails."""

    def __init__(self, message, status_code=None, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class GeminiAPIError(ReviewSystemError):
    """Raised when communication with Gemini fails."""

    def __init__(self, message, status_code=None, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class ParseError(ReviewSystemError):
    """Raised when parsing API responses or local files fails."""

    pass


class ConfigurationError(ReviewSystemError):
    """Raised when required configuration (like API keys) is missing."""

    pass
