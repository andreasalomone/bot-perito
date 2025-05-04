from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    openrouter_api_key: str = Field(..., env="OPENROUTER_API_KEY")
    model_id: str = Field("meta-llama/llama-4-maverick:free", env="MODEL_ID")
    cleanup_ttl: int = Field(900, env="CLEANUP_TTL")           # longer to avoid race
    allow_vision: bool = Field(True, env="ALLOW_VISION")
    max_prompt_chars: int = Field(16000, env="MAX_PROMPT_CHARS")
    reference_dir: Path = Field("app/templates/reference", env="REFERENCE_DIR")
    max_style_paragraphs: int = Field(8, env="MAX_STYLE_PARAS")

    class Config:
        env_file = ".env"

settings = Settings()
