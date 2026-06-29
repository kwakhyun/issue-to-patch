class GiaError(Exception):
    """Base exception for user-facing CLI failures."""


class ConfigError(GiaError):
    """Configuration could not be loaded or validated."""


class IssueLoadError(GiaError):
    """Issue input could not be loaded."""


class GitError(GiaError):
    """Git operation failed."""


class ModelError(GiaError):
    """Model provider call failed."""


class PatchError(GiaError):
    """Patch extraction, validation, or application failed."""


class CommandError(GiaError):
    """Command execution failed unexpectedly."""
