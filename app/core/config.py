from pathlib import Path

from pydantic import Field
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

    supabase_url: str | None = Field(None, env="SUPABASE_URL")
    supabase_anon_key: str | None = Field(None, env="SUPABASE_ANON_KEY")
    supabase_service_role_key: str | None = Field(None, env="SUPABASE_SERVICE_ROLE_KEY")
    ref_dir: Path = Field(Path("data/reference_reports"), env="REF_DIR")
    emb_model_name: str = Field("all-MiniLM-L6-v2", env="EMB_MODEL_NAME")
    api_key: str | None = Field(None, env="API_KEY")

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


settings = Settings()  # type: ignore[call-arg]
