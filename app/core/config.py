from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openrouter_api_key: str | None = Field(None, env="OPENROUTER_API_KEY")
    hf_api_token: str | None = Field(None, env="HF_API_TOKEN")
    model_id: str = Field("meta-llama/llama-4-maverick:free", env="MODEL_ID")
    cleanup_ttl: int = Field(900, env="CLEANUP_TTL")
    allow_vision: bool = Field(True, env="ALLOW_VISION")
    max_prompt_chars: int = Field(4_000_000, env="MAX_PROMPT_CHARS")
    max_total_prompt_chars: int = Field(4_000_000, env="MAX_TOTAL_PROMPT_CHARS")
    reference_dir: Path = Field(Path("app/templates/reference"), env="REFERENCE_DIR")
    template_path: Path = Field(
        Path("app/templates/template.docx"), env="TEMPLATE_PATH"
    )
    max_style_paragraphs: int = Field(8, env="MAX_STYLE_PARAS")
    max_images_in_report: int = Field(10, env="MAX_IMAGES_IN_REPORT")

    api_key: str | None = Field(None, env="API_KEY")

    cors_allowed_origins: list[str] = Field(
        default=[
            "https://aiperito.vercel.app",
            "http://localhost:3000",
            "http://localhost:8000",
            "https://localhost:3000",
            "https://localhost:8000",
        ],
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
        if isinstance(v, str) and v:
            return [origin.strip() for origin in v.split(",")]
        elif isinstance(v, list):
            return v
        # Return the default if env var is empty or not a string/list
        return [
            "https://aiperito.vercel.app",
            "http://localhost:3000",
            "http://localhost:8000",
            "https://localhost:3000",
            "https://localhost:8000",
        ]


settings = Settings()  # type: ignore[call-arg]
