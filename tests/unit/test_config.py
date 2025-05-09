from pathlib import Path

from app.core.config import settings


def test_config_defaults():
    # Ensure default settings have expected types and default values
    assert isinstance(settings.allow_vision, bool)
    assert settings.allow_vision is True
    assert isinstance(settings.max_prompt_chars, int)
    assert settings.max_prompt_chars == 4_000_000
    assert isinstance(settings.template_path, Path)
    assert settings.template_path == Path("app/templates/template.docx")
