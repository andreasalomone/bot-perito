"""Application configuration settings.

This module defines the application-wide settings using Pydantic's BaseSettings.
It allows for loading configurations from environment variables and .env files,
providing type validation and default values.
"""

from pathlib import Path

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Default list of CORS allowed origins
DEFAULT_CORS_ORIGINS = [
    "https://aiperito.vercel.app",
    "https://aiperito.onrender.com",
    "http://localhost:3000",
    "http://localhost:8000",
    "https://localhost:3000",
    "https://localhost:8000",
    "http://0.0.0.0:8000",  # Add this for local development with 0.0.0.0 host
]


class Settings(BaseSettings):
    """Manages application settings, loading them from environment variables or an .env file.

    Attributes:
        openrouter_api_key: API key for OpenRouter services.
        model_id: Identifier for the language model to be used.
        cleanup_ttl: Time-to-live in seconds for temporary files before cleanup.
        max_prompt_chars: Maximum characters allowed for a corpus input before truncation.
        max_total_prompt_chars: Maximum characters allowed for a total assembled prompt.
        template_path: Path to the main DOCX template file.
        max_images_in_report: Maximum number of images to include in the generated report.
        api_key: General API key for securing internal API endpoints.
        ocr_language: Language setting for OCR processing.
        image_thumbnail_width: Width for generated image thumbnails.
        image_thumbnail_height: Height for generated image thumbnails.
        image_jpeg_quality: JPEG quality for generated image thumbnails.
        cors_allowed_origins: List of allowed origins for CORS.
        CRITICAL_FIELDS_FOR_CLARIFICATION: Configuration for fields requiring user clarification.
        LLM_CONNECT_TIMEOUT: LLM client connect timeout in seconds.
        LLM_READ_TIMEOUT: LLM client read timeout in seconds.
    """

    openrouter_api_key: str | None = Field(default=None)
    model_id: str = Field(default="meta-llama/llama-4-maverick:free")
    cleanup_ttl: int = Field(default=900)
    max_prompt_chars: int = Field(default=4_000_000)
    max_total_prompt_chars: int = Field(default=4_000_000)
    template_path: Path = Field(default=Path("app/templates/template.docx"))
    max_images_in_report: int = Field(default=10)

    api_key: str | None = Field(default=None)

    ocr_language: str = Field(default="ita+eng")
    image_thumbnail_width: int = Field(default=512)
    image_thumbnail_height: int = Field(default=512)
    image_jpeg_quality: int = Field(default=70)

    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS),  # Use a copy of the default list
    )

    CRITICAL_FIELDS_FOR_CLARIFICATION: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "polizza": {
                "label": "Numero Polizza",
                "question": "Qual è il numero di polizza?",
            },
            "data_danno": {
                "label": "Data Danno",
                "question": "Qual è la data esatta del danno (GG/MM/AAAA)?",
            },
            "client": {
                "label": "Cliente",
                "question": "Qual è la ragione sociale del cliente?",
            },
            "assicurato": {
                "label": "Assicurato",
                "question": "Qual è la ragione sociale dell'assicurato?",
            },
            "luogo": {
                "label": "Luogo Sinistro",
                "question": "Dove è avvenuto esattamente il sinistro?",
            },
            "cause": {
                "label": "Causa Sinistro",
                "question": "Qual è la causa presunta del sinistro?",
            },
        }
    )

    LLM_CONNECT_TIMEOUT: float = Field(default=10.0, description="LLM client connect timeout in seconds.")
    LLM_READ_TIMEOUT: float = Field(default=180.0, description="LLM client read timeout in seconds.")

    aws_access_key_id: str | None = Field(default=None)
    aws_secret_access_key: str | None = Field(default=None)
    aws_region: str = Field(default="eu-north-1")  # Imposta la tua regione di default qui
    s3_bucket_name: str | None = Field(default=None)
    # TTL per i file su S3 (in ore), usato dal cleanup job S3. Diversoda cleanup_ttl per /tmp.
    s3_cleanup_max_age_hours: int = Field(default=24)

    model_config = {
        "env_file": ".env",
        "protected_namespaces": ("settings_",),
        "env_prefix": "",  # No prefix for environment variables
        "extra": "ignore",  # Ignore extra fields
    }

    @field_validator("cors_allowed_origins", mode="before")  # type: ignore
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str] | None) -> list[str]:
        """Assembles the list of CORS allowed origins.

        If 'v' is a string, it splits it by commas. If 'v' is already a list,
        it's used directly. Otherwise, returns the default list of origins.

        Args:
            v: The value from the environment or direct assignment.

        Returns:
            A list of strings representing allowed CORS origins.
        """
        if isinstance(v, str) and v:
            return [origin.strip() for origin in v.split(",")]
        elif isinstance(v, list):
            return v
        # Return the default if env var is empty or not a string/list
        return list(DEFAULT_CORS_ORIGINS)  # Use a copy of the default list


settings = Settings()
