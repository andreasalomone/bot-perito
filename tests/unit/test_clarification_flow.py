import pytest
from unittest.mock import patch
from fastapi import HTTPException
import json

from app.generation_logic.clarification_flow import build_report_with_clarifications
from app.models.report_models import ClarificationPayload, RequestArtifacts, ReportContext

@pytest.mark.asyncio
async def test_build_report_with_clarifications_merges_and_returns(monkeypatch):
    # Arrange: Prepare base context and clarifications
    base_ctx = ReportContext(client="Mario Rossi", polizza="12345", commento=None)
    clarifications = {"commento": "Nuovo commento"}
    artifacts = RequestArtifacts(
        original_corpus="corpus text",
        image_tokens=[],
        notes="note",
        template_excerpt="template",
        reference_style_text="style text",
        initial_llm_base_fields=base_ctx,
    )
    payload = ClarificationPayload(clarifications=clarifications, request_artifacts=artifacts)

    # Simulate pipeline output: returns a section map
    pipeline_section_map = {"commento": "Nuovo commento pipeline", "extra": "valore extra"}
    pipeline_yield = [
        '{"type": "status", "message": "processing"}',
        json.dumps({"type": "data", "payload": pipeline_section_map})
    ]
    async def fake_run(*args, **kwargs):
        for item in pipeline_yield:
            yield item

    # Patch PipelineService.run
    with patch("app.generation_logic.clarification_flow.PipelineService.run", new=fake_run):
        # Act
        result = await build_report_with_clarifications(payload, request_id="test-req-1")

    # Assert: Clarifications merged, pipeline output merged, result is ReportContext
    assert isinstance(result, ReportContext)
    # The pipeline section_map should override clarifications if keys overlap
    assert result.commento == "Nuovo commento pipeline"
    # Extra fields not in ReportContext should be ignored
    assert not hasattr(result, "extra")
    assert result.client == "Mario Rossi"
    assert result.polizza == "12345"

@pytest.mark.asyncio
async def test_build_report_with_clarifications_pipeline_error(monkeypatch):
    # Arrange: Prepare base context and clarifications
    base_ctx = ReportContext(client="Mario Rossi", polizza="12345", commento=None)
    clarifications = {"commento": "Nuovo commento"}
    artifacts = RequestArtifacts(
        original_corpus="corpus text",
        image_tokens=[],
        notes="note",
        template_excerpt="template",
        reference_style_text="style text",
        initial_llm_base_fields=base_ctx,
    )
    payload = ClarificationPayload(clarifications=clarifications, request_artifacts=artifacts)

    # Simulate pipeline error output
    pipeline_yield = [
        '{"type": "error", "message": "Pipeline failed"}'
    ]
    async def fake_run(*args, **kwargs):
        for item in pipeline_yield:
            yield item

    # Patch PipelineService.run
    with patch("app.generation_logic.clarification_flow.PipelineService.run", new=fake_run):
        # Act & Assert: Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await build_report_with_clarifications(payload, request_id="test-req-2")
        assert "Pipeline failed" in str(exc_info.value.detail)
