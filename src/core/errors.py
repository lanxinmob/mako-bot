class AppError(Exception):
    """Base application error."""


class ConfigError(AppError):
    """Raised when configuration is invalid or missing."""


class NotConfiguredError(ConfigError):
    """Raised when a required integration is not configured."""


class ExternalServiceError(AppError):
    """Raised when an external service call fails."""


class ImageTooLargeError(AppError):
    """Raised when an image exceeds configured size or dimension limits."""


class UnsafeUrlError(AppError):
    """Raised when a server-side fetch targets a non-public or invalid URL."""
