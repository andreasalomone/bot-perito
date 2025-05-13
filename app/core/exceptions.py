"""Core custom exceptions for the application."""


class PipelineError(Exception):
    """Base exception for pipeline-related errors."""


class ConfigurationError(PipelineError):
    """Exception for configuration-related errors (e.g., missing templates, invalid settings)."""
