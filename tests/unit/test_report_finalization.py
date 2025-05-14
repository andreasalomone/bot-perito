import pytest
from fastapi.responses import StreamingResponse
from app.generation_logic.report_finalization import _generate_and_stream_docx, DEFAULT_REPORT_FILENAME, DOCX_MEDIA_TYPE
from app.models.report_models import ReportContext
from app.services.doc_builder import DocBuilderError
from app.core.exceptions import PipelineError

@pytest.mark.asyncio
async def test_generate_and_stream_docx_happy(monkeypatch):
    # Arrange
    fake_bytes = b"docx-content"
    fake_template_path = "template.docx"
    fake_context = ReportContext(client="Mario")
    request_id = "req-1"
    async def fake_inject(template_path, context):
        assert template_path == fake_template_path
        assert context == fake_context
        return fake_bytes
    monkeypatch.setattr("app.generation_logic.report_finalization.inject", fake_inject)
    # Act
    response = await _generate_and_stream_docx(fake_template_path, fake_context, request_id)
    # Assert
    assert isinstance(response, StreamingResponse)
    assert response.media_type == DOCX_MEDIA_TYPE
    assert response.headers["Content-Disposition"] == f"attachment; filename={DEFAULT_REPORT_FILENAME}"
    # Read the streamed content
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    assert body == fake_bytes

@pytest.mark.asyncio
async def test_generate_and_stream_docx_docbuilder_error(monkeypatch):
    # Arrange
    fake_template_path = "template.docx"
    fake_context = ReportContext(client="Mario")
    request_id = "req-2"
    async def fake_inject(template_path, context):
        raise DocBuilderError("doc build fail")
    monkeypatch.setattr("app.generation_logic.report_finalization.inject", fake_inject)
    # Act & Assert
    with pytest.raises(DocBuilderError):
        await _generate_and_stream_docx(fake_template_path, fake_context, request_id)

@pytest.mark.asyncio
async def test_generate_and_stream_docx_generic_error(monkeypatch):
    # Arrange
    fake_template_path = "template.docx"
    fake_context = ReportContext(client="Mario")
    request_id = "req-3"
    async def fake_inject(template_path, context):
        raise Exception("unexpected fail")
    monkeypatch.setattr("app.generation_logic.report_finalization.inject", fake_inject)
    # Act & Assert
    with pytest.raises(PipelineError) as exc_info:
        await _generate_and_stream_docx(fake_template_path, fake_context, request_id)
    assert "unexpected error" in str(exc_info.value).lower()
