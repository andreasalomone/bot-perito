from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.api.routes import (
    _extract_single_file,
    _process_single_image,
    extract_texts,
    process_images,
)

# Import verify_api_key for dependency override
from app.core.security import verify_api_key
from app.main import app  # Assuming app.main.app is your FastAPI instance

# Imports for custom exception types
from app.services.extractor import ExtractorError


# Dummy function to successfully override verify_api_key
async def override_verify_api_key_success():
    return None  # Simulate successful API key verification


@pytest.fixture(scope="module")
def client():
    original_dependency = app.dependency_overrides.get(verify_api_key)
    app.dependency_overrides[verify_api_key] = override_verify_api_key_success
    with TestClient(app) as c:
        yield c
    if original_dependency:
        app.dependency_overrides[verify_api_key] = original_dependency
    else:
        del app.dependency_overrides[verify_api_key]


@pytest.fixture
def patched_temp_dir():
    with patch("app.api.routes.TemporaryDirectory") as mock_temp_dir:
        mock_temp_dir.return_value.__enter__.return_value = "/mock/temp/dir"
        yield mock_temp_dir


# Tests for original helper functions (still in routes.py)
# These tests remain largely unchanged.


@pytest.mark.asyncio
@patch("app.api.routes.extract", new_callable=MagicMock)
async def test_extract_single_file_success(mock_extract):
    mock_extract.return_value = ("Sample text", "image_token")
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.file = MagicMock()

    text, token = await _extract_single_file(mock_file, "test_request_id")

    assert text == "Sample text"
    assert token == "image_token"
    mock_extract.assert_called_once_with("test.pdf", mock_file.file)


@pytest.mark.asyncio
@patch("app.api.routes.extract", new_callable=MagicMock)
async def test_extract_single_file_extractor_error(mock_extract):
    mock_extract.side_effect = ExtractorError("Extraction failed")
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.file = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await _extract_single_file(mock_file, "test_request_id")

    assert exc_info.value.status_code == 400
    assert "Extraction failed" in str(exc_info.value.detail)


@pytest.mark.asyncio
@patch("app.api.routes.extract", new_callable=MagicMock)
async def test_extract_single_file_generic_error(mock_extract):
    mock_extract.side_effect = Exception("Generic error")
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.file = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await _extract_single_file(mock_file, "test_request_id")

    assert exc_info.value.status_code == 400
    assert "Failed to process file test.pdf" in str(exc_info.value.detail)


@pytest.mark.asyncio
@patch("app.api.routes._extract_single_file", new_callable=AsyncMock)
async def test_extract_texts_success(mock_extract_single_file):
    mock_extract_single_file.side_effect = [
        ("Text 1", "Img 1"),
        ("Text 2", None),
        (None, "Img 3"),
    ]
    mock_files = [MagicMock(spec=UploadFile) for _ in range(3)]

    texts, imgs = await extract_texts(mock_files, "test_request_id")

    assert texts == ["Text 1", "Text 2"]
    assert imgs == ["Img 1", "Img 3"]
    assert mock_extract_single_file.call_count == 3


@pytest.mark.asyncio
@patch("app.api.routes._extract_single_file", new_callable=AsyncMock)
async def test_extract_texts_http_exception_propagates(mock_extract_single_file):
    mock_extract_single_file.side_effect = HTTPException(
        status_code=404, detail="File not found"
    )
    mock_files = [MagicMock(spec=UploadFile)]

    with pytest.raises(HTTPException) as exc_info:
        await extract_texts(mock_files, "test_request_id")

    assert exc_info.value.status_code == 404
    assert "File not found" in str(exc_info.value.detail)


@pytest.mark.asyncio
@patch("app.api.routes._extract_single_file", new_callable=AsyncMock)
async def test_extract_texts_other_exception_re_raised(mock_extract_single_file):
    original_exception = ValueError("Some value error")
    # Simulate that one of the gather tasks returns this exception
    mock_extract_single_file.return_value = original_exception
    mock_files = [MagicMock(spec=UploadFile)]

    # Need to adjust how the side_effect is applied for gather returning the exception
    # If _extract_single_file itself raises, gather catches it.
    # If _extract_single_file returns an exception instance (how return_exceptions=True works),
    # then the loop in extract_texts must handle it.
    mock_extract_single_file.side_effect = ValueError(
        "Some value error from side_effect"
    )

    with pytest.raises(ValueError) as exc_info:
        await extract_texts(mock_files, "test_request_id")

    assert str(exc_info.value) == "Some value error from side_effect"


@pytest.mark.asyncio
async def test_extract_texts_empty_input():
    texts, imgs = await extract_texts([], "test_request_id")
    assert texts == []
    assert imgs == []


@pytest.mark.asyncio
@patch("app.api.routes.extract_damage_image", new_callable=MagicMock)
async def test_process_single_image_success(mock_extract_damage_image):
    mock_extract_damage_image.return_value = (None, "damage_image_token")
    mock_image_file = MagicMock(spec=UploadFile)
    mock_image_file.filename = "damage.jpg"
    mock_image_file.file = MagicMock()

    token = await _process_single_image(mock_image_file, "test_request_id")

    assert token == "damage_image_token"
    mock_extract_damage_image.assert_called_once_with(mock_image_file.file)


@pytest.mark.asyncio
@patch("app.api.routes.extract_damage_image", new_callable=MagicMock)
async def test_process_single_image_extractor_error(mock_extract_damage_image):
    mock_extract_damage_image.side_effect = ExtractorError("Image extraction failed")
    mock_image_file = MagicMock(spec=UploadFile)
    mock_image_file.filename = "damage.jpg"
    mock_image_file.file = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await _process_single_image(mock_image_file, "test_request_id")

    assert exc_info.value.status_code == 400
    assert "Image extraction failed" in str(exc_info.value.detail)


@pytest.mark.asyncio
@patch("app.api.routes.extract_damage_image", new_callable=MagicMock)
async def test_process_single_image_generic_error(mock_extract_damage_image):
    mock_extract_damage_image.side_effect = Exception("Generic image error")
    mock_image_file = MagicMock(spec=UploadFile)
    mock_image_file.filename = "damage.jpg"
    mock_image_file.file = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await _process_single_image(mock_image_file, "test_request_id")

    assert exc_info.value.status_code == 400
    assert "Failed to process damage image damage.jpg" in str(exc_info.value.detail)


@pytest.mark.asyncio
@patch("app.api.routes._process_single_image", new_callable=AsyncMock)
async def test_process_images_success(mock_process_single_image):
    mock_process_single_image.side_effect = ["Token1", "Token2"]
    mock_image_files = [MagicMock(spec=UploadFile) for _ in range(2)]

    tokens = await process_images(mock_image_files, "test_request_id")

    assert tokens == ["Token1", "Token2"]
    assert mock_process_single_image.call_count == 2


@pytest.mark.asyncio
async def test_process_images_empty_input():
    tokens = await process_images([], "test_request_id")
    assert tokens == []


@pytest.mark.asyncio
@patch("app.api.routes._process_single_image", new_callable=AsyncMock)
async def test_process_images_http_exception_propagates(mock_process_single_image):
    mock_process_single_image.side_effect = HTTPException(
        status_code=400, detail="Bad image"
    )
    mock_image_files = [MagicMock(spec=UploadFile)]

    with pytest.raises(HTTPException) as exc_info:
        await process_images(mock_image_files, "test_request_id")

    assert exc_info.value.status_code == 400
    assert "Bad image" in str(exc_info.value.detail)


@pytest.mark.asyncio
@patch("app.api.routes._process_single_image", new_callable=AsyncMock)
async def test_process_images_other_exception_re_raised(mock_process_single_image):
    original_exception_message = "Corrupt image data from side_effect"
    mock_process_single_image.side_effect = ValueError(original_exception_message)
    mock_image_files = [MagicMock(spec=UploadFile)]

    with pytest.raises(ValueError) as exc_info:
        await process_images(mock_image_files, "test_request_id")

    assert str(exc_info.value) == original_exception_message


# Tests for /generate endpoint (refactored)


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._run_processing_pipeline", new_callable=AsyncMock)
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
@patch("app.api.routes.settings")
async def test_generate_endpoint_success_minimal_refactored(
    mock_settings,
    mock_generate_and_stream_docx,
    mock_run_processing_pipeline,
    mock_extract_base_context,
    mock_retrieve_similar_cases,
    mock_load_template_excerpt,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template.docx"
    mock_validate_and_extract_files.return_value = (
        "Guarded corpus",
        ["img_token1", "damage_img_token1"],
    )
    mock_load_template_excerpt.return_value = "Template excerpt part"
    mock_retrieve_similar_cases.return_value = [
        {"title": "Similar Case 1", "content_snippet": "Snippet 1"}
    ]
    mock_extract_base_context.return_value = {
        "cliente": "Test Client",
        "polizza": "123",
    }
    mock_run_processing_pipeline.return_value = {"section1": "Content 1"}
    mock_generate_and_stream_docx.return_value = StreamingResponse(
        content=iter([b"mock docx content for minimal test"])
    )

    files_data = {
        "files": ("test_doc.pdf", b"dummy file content for test", "application/pdf")
    }
    form_data = {"notes": "Test notes for generation", "use_rag": "true"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 200
    mock_validate_and_extract_files.assert_called_once()
    request_id_arg = mock_validate_and_extract_files.call_args[0][2]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Guarded corpus", True, request_id_arg
    )
    mock_extract_base_context.assert_called_once_with(
        "Template excerpt part",
        "Guarded corpus",
        ["img_token1", "damage_img_token1"],
        "Test notes for generation",
        [{"title": "Similar Case 1", "content_snippet": "Snippet 1"}],
        request_id_arg,
    )
    mock_run_processing_pipeline.assert_called_once_with(
        "Template excerpt part",
        "Guarded corpus",
        ["img_token1", "damage_img_token1"],
        "Test notes for generation",
        [{"title": "Similar Case 1", "content_snippet": "Snippet 1"}],
        request_id_arg,
    )
    expected_final_ctx = {
        "cliente": "Test Client",
        "polizza": "123",
        "section1": "Content 1",
    }
    mock_generate_and_stream_docx.assert_called_once_with(
        str(mock_settings.template_path), expected_final_ctx, request_id_arg
    )
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._run_processing_pipeline", new_callable=AsyncMock)
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
@patch("app.api.routes.settings")
async def test_generate_endpoint_success_no_rag_refactored(
    mock_settings,
    mock_generate_and_stream_docx,
    mock_run_processing_pipeline,
    mock_extract_base_context,
    mock_retrieve_similar_cases,
    mock_load_template_excerpt,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template_no_rag.docx"
    mock_validate_and_extract_files.return_value = ("Guarded corpus no RAG", [])
    mock_load_template_excerpt.return_value = "Template excerpt no RAG"
    mock_retrieve_similar_cases.return_value = []
    mock_extract_base_context.return_value = {"cliente": "Client No RAG"}
    mock_run_processing_pipeline.return_value = {"section_no_rag": "Content no RAG"}
    mock_generate_and_stream_docx.return_value = StreamingResponse(
        content=iter([b"mock docx content for no rag test"])
    )

    files_data = {"files": ("test.pdf", b"dummy", "application/pdf")}
    form_data = {"notes": "Notes no RAG", "use_rag": "false"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 200
    request_id_arg = mock_validate_and_extract_files.call_args[0][2]

    mock_validate_and_extract_files.assert_called_once()
    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Guarded corpus no RAG", False, request_id_arg
    )
    mock_extract_base_context.assert_called_once_with(
        "Template excerpt no RAG",
        "Guarded corpus no RAG",
        [],
        "Notes no RAG",
        [],
        request_id_arg,
    )
    mock_run_processing_pipeline.assert_called_once_with(
        "Template excerpt no RAG",
        "Guarded corpus no RAG",
        [],
        "Notes no RAG",
        [],
        request_id_arg,
    )
    expected_final_ctx = {
        "cliente": "Client No RAG",
        "section_no_rag": "Content no RAG",
    }
    mock_generate_and_stream_docx.assert_called_once_with(
        str(mock_settings.template_path), expected_final_ctx, request_id_arg
    )
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
async def test_generate_endpoint_template_load_failure_refactored(
    mock_load_template_excerpt,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_validate_and_extract_files.return_value = ("Corpus", [])
    mock_load_template_excerpt.side_effect = HTTPException(
        status_code=500, detail="Template loading failed for excerpt"
    )

    files_data = {"files": ("test.pdf", b"dummy", "application/pdf")}
    form_data = {"notes": "Test notes", "use_rag": "false"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 500
    response_data = response.json()
    assert "detail" in response_data
    assert "Template loading failed for excerpt" in response_data["detail"]

    mock_validate_and_extract_files.assert_called_once()
    mock_load_template_excerpt.assert_called_once()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_validation_failure_refactored(
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_validate_and_extract_files.side_effect = HTTPException(
        status_code=400, detail="Invalid file type"
    )

    files_data = {"files": ("invalid.txt", b"dummy content", "text/plain")}
    form_data = {"notes": "Test notes", "use_rag": "false"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 400
    response_data = response.json()
    assert "detail" in response_data
    assert "Invalid file type" in response_data["detail"]

    mock_validate_and_extract_files.assert_called_once()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
async def test_generate_endpoint_rag_error_refactored(
    mock_retrieve_similar_cases,
    mock_load_template_excerpt,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_validate_and_extract_files.return_value = ("Corpus for RAG error", [])
    mock_load_template_excerpt.return_value = "Template for RAG error"
    mock_retrieve_similar_cases.side_effect = HTTPException(
        status_code=500, detail="RAG processing failed: RAG service failed"
    )

    files_data = {"files": ("test.pdf", b"dummy", "application/pdf")}
    form_data = {"notes": "Notes for RAG error", "use_rag": "true"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 500
    response_data = response.json()
    assert "detail" in response_data
    assert "RAG processing failed: RAG service failed" in response_data["detail"]

    mock_validate_and_extract_files.assert_called_once()
    mock_load_template_excerpt.assert_called_once()
    mock_retrieve_similar_cases.assert_called_once()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
# No need to mock _run_processing_pipeline if _extract_base_context fails
async def test_generate_endpoint_llm_error_refactored(
    mock_extract_base_context,
    mock_retrieve_similar_cases,
    mock_load_template_excerpt,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_validate_and_extract_files.return_value = ("Corpus", [])
    mock_load_template_excerpt.return_value = "Template"
    mock_retrieve_similar_cases.return_value = []
    mock_extract_base_context.side_effect = HTTPException(
        status_code=500,
        detail="LLM processing for base fields failed: LLM processing failed",
    )

    files_data = {"files": ("test.pdf", b"dummy", "application/pdf")}
    form_data = {"notes": "Notes", "use_rag": "false"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 500
    response_data = response.json()
    assert "detail" in response_data
    assert (
        "LLM processing for base fields failed: LLM processing failed"
        in response_data["detail"]
    )

    mock_validate_and_extract_files.assert_called_once()
    mock_load_template_excerpt.assert_called_once()
    mock_retrieve_similar_cases.assert_called_once()
    mock_extract_base_context.assert_called_once()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._run_processing_pipeline", new_callable=AsyncMock)
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
@patch("app.api.routes.settings")
async def test_generate_endpoint_pipeline_error_refactored(
    mock_settings,
    mock_generate_and_stream_docx,
    mock_run_processing_pipeline,
    mock_extract_base_context,
    mock_retrieve_similar_cases,
    mock_load_template_excerpt,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template.docx"
    mock_validate_and_extract_files.return_value = ("Corpus for pipeline error", [])
    mock_load_template_excerpt.return_value = "Template for pipeline error"
    mock_retrieve_similar_cases.return_value = []
    mock_extract_base_context.return_value = {"base_field": "base_value"}

    error_message = "Pipeline processing failed: Test pipeline error from helper"
    mock_run_processing_pipeline.side_effect = HTTPException(
        status_code=500, detail=error_message
    )

    files_data = {
        "files": ("test.pdf", b"dummy data for pipeline error", "application/pdf")
    }
    form_data = {"notes": "Notes for pipeline error test", "use_rag": "false"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 500
    response_data = response.json()
    assert "detail" in response_data
    assert error_message in response_data["detail"]

    mock_validate_and_extract_files.assert_called_once()
    request_id_arg = mock_validate_and_extract_files.call_args[0][2]
    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Corpus for pipeline error", False, request_id_arg
    )
    mock_extract_base_context.assert_called_once_with(
        "Template for pipeline error",
        "Corpus for pipeline error",
        [],
        "Notes for pipeline error test",
        [],
        request_id_arg,
    )
    mock_run_processing_pipeline.assert_called_once_with(
        "Template for pipeline error",
        "Corpus for pipeline error",
        [],
        "Notes for pipeline error test",
        [],
        request_id_arg,
    )
    mock_generate_and_stream_docx.assert_not_called()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes.settings")
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._run_processing_pipeline", new_callable=AsyncMock)
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
async def test_generate_endpoint_image_truncation_refactored(
    mock_generate_and_stream_docx,
    mock_run_processing_pipeline,
    mock_extract_base_context,
    mock_retrieve_similar_cases,
    mock_load_template_excerpt,
    mock_settings,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template.docx"
    expected_truncated_images = [f"img_token_{i}" for i in range(7)] + [
        f"damage_token_{i}" for i in range(3)
    ]
    mock_validate_and_extract_files.return_value = (
        "corpus for truncation",
        expected_truncated_images,
    )

    mock_load_template_excerpt.return_value = "template excerpt"
    mock_retrieve_similar_cases.return_value = []
    mock_extract_base_context.return_value = {"base_field": "value"}
    mock_run_processing_pipeline.return_value = {"section_map_field": "section_value"}
    mock_generate_and_stream_docx.return_value = StreamingResponse(
        content=iter([b"mock docx content for truncation test"])
    )

    files_data = {"files": ("f.pdf", b"d", "application/pdf")}
    all_files_data = files_data
    form_data = {"notes": "notes for truncation", "use_rag": "false"}

    response = client.post("/generate", files=all_files_data, data=form_data)

    mock_validate_and_extract_files.assert_called_once()

    assert response.status_code == 200

    request_id_arg = mock_validate_and_extract_files.call_args[0][2]

    mock_extract_base_context.assert_called_once_with(
        "template excerpt",
        "corpus for truncation",
        expected_truncated_images,
        "notes for truncation",
        [],
        request_id_arg,
    )
    mock_run_processing_pipeline.assert_called_once_with(
        "template excerpt",
        "corpus for truncation",
        expected_truncated_images,
        "notes for truncation",
        [],
        request_id_arg,
    )
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_generic_unexpected_error(
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    unexpected_error_message = "A very unexpected problem!"
    mock_validate_and_extract_files.side_effect = RuntimeError(unexpected_error_message)

    files_data = {"files": ("test.pdf", b"dummy", "application/pdf")}
    form_data = {"notes": "Test notes", "use_rag": "false"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 500
    response_data = response.json()
    assert "detail" in response_data
    assert "An unexpected internal error occurred (id: " in response_data["detail"]
    assert "). Please contact support." in response_data["detail"]

    mock_validate_and_extract_files.assert_called_once()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._run_processing_pipeline", new_callable=AsyncMock)
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
@patch("app.api.routes.settings")
async def test_generate_endpoint_doc_builder_error_refactored(
    mock_settings,
    mock_generate_and_stream_docx,
    mock_run_processing_pipeline,
    mock_extract_base_context,
    mock_retrieve_similar_cases,
    mock_load_template_excerpt,
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template.docx"
    mock_validate_and_extract_files.return_value = ("Corpus for docbuild error", [])
    mock_load_template_excerpt.return_value = "Template for docbuild error"
    mock_retrieve_similar_cases.return_value = []
    mock_extract_base_context.return_value = {"base": "context_docbuild"}
    mock_run_processing_pipeline.return_value = {"section": "map_docbuild"}
    error_message = "Document builder error: Failed to build DOCX in test"
    mock_generate_and_stream_docx.side_effect = HTTPException(
        status_code=500, detail=error_message
    )

    files_data = {"files": ("test.pdf", b"dummy", "application/pdf")}
    form_data = {"notes": "Notes for docbuild error", "use_rag": "false"}

    response = client.post("/generate", files=files_data, data=form_data)

    assert response.status_code == 500
    response_data = response.json()
    assert "detail" in response_data
    assert error_message in response_data["detail"]

    mock_validate_and_extract_files.assert_called_once()
    request_id_arg = mock_validate_and_extract_files.call_args[0][2]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Corpus for docbuild error", False, request_id_arg
    )
    mock_extract_base_context.assert_called_once_with(
        "Template for docbuild error",
        "Corpus for docbuild error",
        [],
        "Notes for docbuild error",
        [],
        request_id_arg,
    )
    mock_run_processing_pipeline.assert_called_once_with(
        "Template for docbuild error",
        "Corpus for docbuild error",
        [],
        "Notes for docbuild error",
        [],
        request_id_arg,
    )
    expected_final_ctx_before_inject = {
        "base": "context_docbuild",
        "section": "map_docbuild",
    }
    mock_generate_and_stream_docx.assert_called_once_with(
        str(mock_settings.template_path),
        expected_final_ctx_before_inject,
        request_id_arg,
    )
    patched_temp_dir.assert_called_once()
