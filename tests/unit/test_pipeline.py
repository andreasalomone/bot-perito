from unittest.mock import AsyncMock

import pytest

from app.services.llm import LLMError
from app.services.pipeline import PipelineError, PipelineService


@pytest.mark.asyncio
async def test_generate_outline_success(monkeypatch):
    dummy = '[{"section":"dinamica_eventi","title":"Dinamica Evento","bullets":["p1","p2","p3"]}]'
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value=dummy),
        raising=False,
    )
    service = PipelineService()
    result = await service.generate_outline("T", "C", [], "N", [])
    assert isinstance(result, list)
    assert result[0]["section"] == "dinamica_eventi"


@pytest.mark.asyncio
async def test_generate_outline_invalid_json(monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value="not json"),
        raising=False,
    )
    service = PipelineService()
    with pytest.raises(PipelineError) as exc:
        await service.generate_outline("T", "C", [], "N", [])
    assert "Failed to generate outline" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_outline_empty_list(monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value="[]"),
        raising=False,
    )
    service = PipelineService()
    with pytest.raises(PipelineError) as exc:
        await service.generate_outline("T", "C", [], "N", [])
    assert "Invalid outline format" in str(exc.value)


@pytest.mark.asyncio
async def test_expand_section_success(monkeypatch):
    dummy = '{"sec":"content"}'
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value=dummy),
        raising=False,
    )
    section = {"section": "sec", "title": "SecTitle", "bullets": ["b1"]}
    context = {
        "corpus": "cor",
        "template_excerpt": "tmpl",
        "similar": ["sim"],
        "notes": "n",
    }
    service = PipelineService()
    result = await service.expand_section(section, context)
    assert result == "content"


@pytest.mark.asyncio
async def test_expand_section_empty(monkeypatch):
    dummy = '{"sec":""}'
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value=dummy),
        raising=False,
    )
    section = {"section": "sec", "title": "SecTitle", "bullets": ["b1"]}
    context = {"corpus": "", "template_excerpt": "", "similar": [], "notes": ""}
    service = PipelineService()
    with pytest.raises(PipelineError) as exc:
        await service.expand_section(section, context)
    assert "Empty content for section SecTitle" in str(exc.value)


@pytest.mark.asyncio
async def test_expand_section_json_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value="not json"),
        raising=False,
    )
    section = {"section": "sec", "title": "SecTitle", "bullets": []}
    context = {"corpus": "", "template_excerpt": "", "similar": [], "notes": ""}
    service = PipelineService()
    with pytest.raises(PipelineError) as exc:
        await service.expand_section(section, context)
    assert "Failed to expand section SecTitle" in str(exc.value)


@pytest.mark.asyncio
async def test_harmonize_success(monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value='{"a": "unified text a", "b": "unified text b"}'),
        raising=False,
    )
    service = PipelineService()
    result = await service.harmonize({"a": "1", "b": "2"}, extra_styles="dummy_style")
    assert isinstance(result, dict)
    assert result.get("a") == "unified text a"


@pytest.mark.asyncio
async def test_harmonize_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(return_value="{}"),
        raising=False,
    )
    service = PipelineService()
    with pytest.raises(PipelineError) as exc:
        await service.harmonize({"a": "1"}, extra_styles="dummy_style")
    assert "Harmonization returned invalid structure or missed sections." in str(
        exc.value
    )


@pytest.mark.asyncio
async def test_harmonize_api_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.pipeline.call_llm",
        AsyncMock(side_effect=LLMError("err")),
        raising=False,
    )
    service = PipelineService()
    with pytest.raises(PipelineError) as exc:
        await service.harmonize({"a": "1"}, extra_styles="dummy_style")
    assert "Failed to harmonize sections" in str(exc.value)
