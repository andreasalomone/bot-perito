import pytest
from unittest.mock import MagicMock
from app.generation_logic.context_preparation import _load_template_excerpt, _extract_base_context
from app.core.exceptions import ConfigurationError, PipelineError
from app.services.llm import LLMError, JSONParsingError

@pytest.mark.asyncio
async def test_load_template_excerpt_happy(monkeypatch):
    # Arrange
    fake_excerpt = "Paragraph 1\nParagraph 2"
    async def fake_to_thread(func, path):
        return fake_excerpt
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    # Act
    result = await _load_template_excerpt("fake_path.docx", request_id="req-1")
    # Assert
    assert result == fake_excerpt

@pytest.mark.asyncio
async def test_load_template_excerpt_package_not_found(monkeypatch):
    # Arrange
    from docx.opc.exceptions import PackageNotFoundError
    async def fake_to_thread(func, path):
        raise PackageNotFoundError("not found")
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    # Act & Assert
    with pytest.raises(ConfigurationError) as exc_info:
        await _load_template_excerpt("bad_path.docx", request_id="req-2")
    assert "Template file not found" in str(exc_info.value)

@pytest.mark.asyncio
async def test_load_template_excerpt_other_error(monkeypatch):
    async def fake_to_thread(func, path):
        raise Exception("other error")
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    with pytest.raises(ConfigurationError) as exc_info:
        await _load_template_excerpt("bad_path.docx", request_id="req-3")
    assert "Unexpected error loading template excerpt" in str(exc_info.value)

@pytest.mark.asyncio
async def test_extract_base_context_happy(monkeypatch):
    # Arrange
    fake_prompt = "prompt"
    fake_raw_base = "{\"client\": \"Mario\"}"
    fake_ctx = {"client": "Mario"}
    monkeypatch.setattr("app.generation_logic.context_preparation.build_prompt", lambda *a, **k: fake_prompt)
    async def fake_call_llm(prompt):
        assert prompt == fake_prompt
        return fake_raw_base
    monkeypatch.setattr("app.generation_logic.context_preparation.call_llm", fake_call_llm)
    monkeypatch.setattr("app.generation_logic.context_preparation.extract_json", lambda raw: fake_ctx)
    class FakeSettings:
        max_total_prompt_chars = 10000
    monkeypatch.setattr("app.generation_logic.context_preparation.settings", FakeSettings())
    # Act
    result = await _extract_base_context("te", "corpus", [], "notes", "req-4", "style")
    # Assert
    assert result == fake_ctx

@pytest.mark.asyncio
async def test_extract_base_context_prompt_too_large(monkeypatch):
    monkeypatch.setattr("app.generation_logic.context_preparation.build_prompt", lambda *a, **k: "x" * 10001)
    class FakeSettings:
        max_total_prompt_chars = 10000
    monkeypatch.setattr("app.generation_logic.context_preparation.settings", FakeSettings())
    with pytest.raises(PipelineError) as exc_info:
        await _extract_base_context("te", "corpus", [], "notes", "req-5", "style")
    assert "Prompt too large" in str(exc_info.value)

@pytest.mark.asyncio
async def test_extract_base_context_llm_error(monkeypatch):
    monkeypatch.setattr("app.generation_logic.context_preparation.build_prompt", lambda *a, **k: "prompt")
    async def fake_call_llm(prompt):
        raise LLMError("llm fail")
    monkeypatch.setattr("app.generation_logic.context_preparation.call_llm", fake_call_llm)
    monkeypatch.setattr("app.generation_logic.context_preparation.extract_json", lambda raw: {})
    class FakeSettings:
        max_total_prompt_chars = 10000
    monkeypatch.setattr("app.generation_logic.context_preparation.settings", FakeSettings())
    with pytest.raises(LLMError):
        await _extract_base_context("te", "corpus", [], "notes", "req-6", "style")

@pytest.mark.asyncio
async def test_extract_base_context_json_error(monkeypatch):
    monkeypatch.setattr("app.generation_logic.context_preparation.build_prompt", lambda *a, **k: "prompt")
    async def fake_call_llm(prompt):
        return "bad json"
    monkeypatch.setattr("app.generation_logic.context_preparation.call_llm", fake_call_llm)
    def fake_extract_json(raw):
        raise JSONParsingError("json fail")
    monkeypatch.setattr("app.generation_logic.context_preparation.extract_json", fake_extract_json)
    class FakeSettings:
        max_total_prompt_chars = 10000
    monkeypatch.setattr("app.generation_logic.context_preparation.settings", FakeSettings())
    with pytest.raises(JSONParsingError):
        await _extract_base_context("te", "corpus", [], "notes", "req-7", "style")

@pytest.mark.asyncio
async def test_extract_base_context_unexpected_error(monkeypatch):
    monkeypatch.setattr("app.generation_logic.context_preparation.build_prompt", lambda *a, **k: "prompt")
    async def fake_call_llm(prompt):
        raise Exception("unexpected fail")
    monkeypatch.setattr("app.generation_logic.context_preparation.call_llm", fake_call_llm)
    monkeypatch.setattr("app.generation_logic.context_preparation.extract_json", lambda raw: {})
    class FakeSettings:
        max_total_prompt_chars = 10000
    monkeypatch.setattr("app.generation_logic.context_preparation.settings", FakeSettings())
    with pytest.raises(PipelineError) as exc_info:
        await _extract_base_context("te", "corpus", [], "notes", "req-8", "style")
    assert "Unexpected error during base context extraction" in str(exc_info.value)
