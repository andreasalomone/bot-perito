from unittest.mock import AsyncMock

import pytest

import app.services.llm  # Import the module itself
from app.core.config import settings
from app.services.llm import (
    JSONParsingError,
    LLMError,
    build_prompt,
    call_llm,
    extract_json,
)


@pytest.mark.asyncio
async def test_call_llm_success(monkeypatch):
    # Setup dummy response object with nested choices -> message -> content
    class DummyMessage:
        def __init__(self, content):
            self.content = content

    class DummyChoice:
        def __init__(self, message):
            self.message = message

    class DummyResponse:
        def __init__(self, content):
            self.choices = [DummyChoice(DummyMessage(content))]

    # Monkeypatch the OpenAI client create method
    monkeypatch.setattr(
        "app.services.llm.client.chat.completions.create",
        AsyncMock(return_value=DummyResponse("  test_content  ")),
    )

    result = await call_llm("prompt text")
    assert result == "test_content"


@pytest.mark.asyncio
async def test_call_llm_api_error(monkeypatch):
    from openai import OpenAIError

    # Monkeypatch to raise API error
    monkeypatch.setattr(
        "app.services.llm.client.chat.completions.create",
        AsyncMock(side_effect=OpenAIError("api error")),
    )

    with pytest.raises(LLMError) as exc:
        await call_llm("prompt text")
    assert "OpenAI API error" in str(exc.value)


def test_extract_json_plain():
    text = '{"a": 1}'
    result = extract_json(text)
    assert result == {"a": 1}


def test_extract_json_embedded():
    text = 'prefix {"b":2} suffix'
    result = extract_json(text)
    assert result == {"b": 2}


def test_extract_json_no_json():
    with pytest.raises(JSONParsingError):
        extract_json("no json here")


def test_extract_json_bad_inside():
    with pytest.raises(JSONParsingError):
        extract_json('blah {"a": }')


def test_build_prompt_sections(monkeypatch):
    # Monkeypatch style samples and settings
    monkeypatch.setattr(
        "app.services.llm.load_style_samples",
        lambda: "STYLE_SAMPLE",
    )
    monkeypatch.setattr(settings, "allow_vision", True, raising=False)

    prompt = build_prompt(
        template_excerpt="TEX",
        corpus="CORPUS",
        images=["IMG1", "IMG2"],
        notes="NOTES",
    )

    # Verify composition
    assert "TEX" in prompt
    assert "CORPUS" in prompt
    assert "NOTES" in prompt
    assert "STYLE_SAMPLE" in prompt
    assert "FOTO_DANNI_BASE64" in prompt
    assert "IMG1" in prompt and "IMG2" in prompt


def test_build_prompt_no_vision_or_styles(monkeypatch):
    monkeypatch.setattr(app.services.llm.settings, "allow_vision", False, raising=False)
    monkeypatch.setattr(
        "app.services.llm.load_style_samples",
        lambda: "",
    )

    prompt = build_prompt(
        template_excerpt="TM",
        corpus="C",
        images=["IMG"],
        notes="N",
    )

    assert "FOTO_DANNI_BASE64:\n" not in prompt
