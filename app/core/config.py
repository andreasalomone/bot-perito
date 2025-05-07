from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openrouter_api_key: str = Field(..., env="OPENROUTER_API_KEY")
    model_id: str = Field("meta-llama/llama-4-maverick:free", env="MODEL_ID")
    cleanup_ttl: int = Field(900, env="CLEANUP_TTL")
    allow_vision: bool = Field(True, env="ALLOW_VISION")
    max_prompt_chars: int = Field(4_000_000, env="MAX_PROMPT_CHARS")
    max_total_prompt_chars: int = Field(4_000_000, env="MAX_TOTAL_PROMPT_CHARS")
    reference_dir: Path = Field(Path("app/templates/reference"), env="REFERENCE_DIR")
    max_style_paragraphs: int = Field(8, env="MAX_STYLE_PARAS")

    supabase_url: str = Field(..., env="SUPABASE_URL")
    supabase_anon_key: str = Field(..., env="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(..., env="SUPABASE_SERVICE_ROLE_KEY")
    ref_dir: Path = Field(Path("data/reference_reports"), env="REF_DIR")
    emb_model_name: str = Field("all-MiniLM-L6-v2", env="EMB_MODEL_NAME")
    api_key: str = Field(..., env="API_KEY")

    model_config = {"env_file": ".env", "protected_namespaces": ("settings_",)}  # type: ignore[typeddict-unknown-key]


settings = Settings()  # type: ignore[call-arg]
