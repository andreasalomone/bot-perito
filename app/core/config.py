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
    "http://localhost:3000",
    "http://localhost:8000",
    "https://localhost:3000",
    "https://localhost:8000",
]


class Settings(BaseSettings):
    """Manages application settings, loading them from environment variables or an .env file.

    Attributes:
        openrouter_api_key: API key for OpenRouter services.
        model_id: Identifier for the language model to be used.
        cleanup_ttl: Time-to-live in seconds for temporary files before cleanup.
        max_prompt_chars: Maximum characters allowed for a corpus input before truncation.
        max_total_prompt_chars: Maximum characters allowed for a total assembled prompt.
        reference_dir: Path to the directory containing reference style documents.
        template_path: Path to the main DOCX template file.
        max_style_paragraphs: Maximum number of paragraphs to extract from style reference documents.
        max_images_in_report: Maximum number of images to include in the generated report.
        api_key: General API key for securing internal API endpoints.
        ocr_language: Language setting for OCR processing.
        image_thumbnail_width: Width for generated image thumbnails.
        image_thumbnail_height: Height for generated image thumbnails.
        image_jpeg_quality: JPEG quality for generated image thumbnails.
        cors_allowed_origins: List of allowed origins for CORS.
        CRITICAL_FIELDS_FOR_CLARIFICATION: Configuration for fields requiring user clarification.
    """

    openrouter_api_key: str | None = Field(None, env="OPENROUTER_API_KEY")
    model_id: str = Field("meta-llama/llama-4-maverick:free", env="MODEL_ID")
    cleanup_ttl: int = Field(900, env="CLEANUP_TTL")
    max_prompt_chars: int = Field(4_000_000, env="MAX_PROMPT_CHARS")
    max_total_prompt_chars: int = Field(4_000_000, env="MAX_TOTAL_PROMPT_CHARS")
    reference_dir: Path = Field(Path("app/templates/reference"), env="REFERENCE_DIR")
    template_path: Path = Field(Path("app/templates/template.docx"), env="TEMPLATE_PATH")
    max_style_paragraphs: int = Field(8, env="MAX_STYLE_PARAS")
    max_images_in_report: int = Field(10, env="MAX_IMAGES_IN_REPORT")

    api_key: str | None = Field(None, env="API_KEY")

    ocr_language: str = Field("ita", env="OCR_LANGUAGE")
    image_thumbnail_width: int = Field(512, env="IMAGE_THUMBNAIL_WIDTH")
    image_thumbnail_height: int = Field(512, env="IMAGE_THUMBNAIL_HEIGHT")
    image_jpeg_quality: int = Field(70, env="IMAGE_JPEG_QUALITY")

    cors_allowed_origins: list[str] = Field(
        default=list(DEFAULT_CORS_ORIGINS),  # Use a copy of the default list
        env="CORS_ALLOWED_ORIGINS",
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

    model_config = {"env_file": ".env", "protected_namespaces": ("settings_",)}

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
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
