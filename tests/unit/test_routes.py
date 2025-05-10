import asyncio  # Added for asyncio.sleep
import json
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

# New imports for clarification feature tests
from app.services.doc_builder import DocBuilderError

# Imports for custom exception types
from app.services.extractor import ExtractorError
from app.services.pipeline import PipelineError


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

    assert exc_info.value.status_code == 500
    assert "An unexpected error occurred during text extraction." in str(
        exc_info.value.detail
    )


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
    # original_exception = ValueError("Some value error") # Not used
    mock_extract_single_file.side_effect = ValueError(
        "Some value error from side_effect"
    )
    mock_files = [MagicMock(spec=UploadFile)]

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

    assert exc_info.value.status_code == 500
    assert "An unexpected error occurred during image processing." in str(
        exc_info.value.detail
    )


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
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_success_minimal_refactored(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,  # Injected mock for the PipelineService class
    mock_settings,
    mock_uuid4,
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
    pipeline_section_map = {"section1": "Content 1 from pipeline"}

    # Configure the mocked PipelineService instance's run method
    mock_pipeline_instance = MockPipelineService.return_value

    async def mock_pipeline_run_gen_success(*args, **kwargs):  # Ensure it accepts args
        yield json.dumps({"type": "status", "message": "Pipeline progress..."})
        await asyncio.sleep(0)
        yield json.dumps({"type": "data", "payload": pipeline_section_map})

    mock_pipeline_instance.run = MagicMock(side_effect=mock_pipeline_run_gen_success)

    file_tuple = ("test_doc.pdf", b"dummy file content for test", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Test notes for generation", "use_rag": "true"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200

    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

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
    # Check that the 'run' method on the instance was called
    mock_pipeline_instance.run.assert_called_once_with(
        "Template excerpt part",
        "Guarded corpus",
        ["img_token1", "damage_img_token1"],
        "Test notes for generation",
        [{"title": "Similar Case 1", "content_snippet": "Snippet 1"}],
        extra_styles="",
    )

    final_data_event = None
    for item in streamed_data:
        if item.get("type") == "data" and "payload" in item:
            final_data_event = item
            break

    assert final_data_event is not None, "Final 'data' event not found in stream"

    expected_final_payload = {
        "cliente": "Test Client",
        "polizza": "123",
        **pipeline_section_map,
    }
    assert (
        final_data_event["payload"] == expected_final_payload
    ), f"Final payload mismatch. Expected {expected_final_payload}, Got {final_data_event['payload']}"

    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_success_no_rag_refactored(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,
    mock_settings,
    mock_uuid4,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template_no_rag.docx"
    mock_validate_and_extract_files.return_value = ("Guarded corpus no RAG", [])
    mock_load_template_excerpt.return_value = "Template excerpt no RAG"
    mock_retrieve_similar_cases.return_value = []
    base_ctx_no_rag = {"cliente": "Client No RAG"}
    mock_extract_base_context.return_value = base_ctx_no_rag

    pipeline_section_map_no_rag = {"section_no_rag": "Content no RAG"}

    mock_pipeline_instance = MockPipelineService.return_value

    async def mock_pipeline_run_gen_no_rag_success(
        *args, **kwargs
    ):  # Ensure it accepts args
        yield json.dumps({"type": "status", "message": "Pipeline for no RAG"})
        await asyncio.sleep(0)
        yield json.dumps({"type": "data", "payload": pipeline_section_map_no_rag})

    mock_pipeline_instance.run = MagicMock(
        side_effect=mock_pipeline_run_gen_no_rag_success
    )

    file_tuple = ("test.pdf", b"dummy", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Notes no RAG", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    mock_validate_and_extract_files.assert_called_once()
    _, _, request_id_arg_val = mock_validate_and_extract_files.call_args[0]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg_val
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Guarded corpus no RAG", False, request_id_arg_val
    )
    mock_extract_base_context.assert_called_once_with(
        "Template excerpt no RAG",
        "Guarded corpus no RAG",
        [],
        "Notes no RAG",
        [],
        request_id_arg_val,
    )
    mock_pipeline_instance.run.assert_called_once_with(
        "Template excerpt no RAG",
        "Guarded corpus no RAG",
        [],
        "Notes no RAG",
        [],
        extra_styles="",
    )

    final_data_event = next(
        (item for item in streamed_data if item.get("type") == "data"), None
    )
    assert final_data_event is not None, "Final 'data' event not found in stream"
    expected_final_payload = {**base_ctx_no_rag, **pipeline_section_map_no_rag}
    assert final_data_event["payload"] == expected_final_payload
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_image_truncation_refactored(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,
    mock_settings,
    mock_uuid4,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template_truncation.docx"
    original_images = [f"img_token_{i}" for i in range(15)]
    expected_truncated_images = original_images[:10]

    mock_validate_and_extract_files.return_value = (
        "corpus for truncation",
        expected_truncated_images,
    )

    mock_load_template_excerpt.return_value = "template excerpt for truncation"
    mock_retrieve_similar_cases.return_value = []
    base_ctx_trunc = {"base_field": "value_trunc"}
    mock_extract_base_context.return_value = base_ctx_trunc

    pipeline_section_map_trunc = {"section_map_field": "section_value_trunc"}

    mock_pipeline_instance = MockPipelineService.return_value

    async def mock_pipeline_run_gen_trunc_success(
        *args, **kwargs
    ):  # Ensure it accepts args
        yield json.dumps({"type": "status", "message": "Pipeline for truncation"})
        await asyncio.sleep(0)
        yield json.dumps({"type": "data", "payload": pipeline_section_map_trunc})

    mock_pipeline_instance.run = MagicMock(
        side_effect=mock_pipeline_run_gen_trunc_success
    )

    file_tuple = ("f_trunc.pdf", b"d_trunc", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "notes for truncation", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    mock_validate_and_extract_files.assert_called_once()
    _, _, request_id_arg_val = mock_validate_and_extract_files.call_args[0]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg_val
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "corpus for truncation", False, request_id_arg_val
    )
    mock_extract_base_context.assert_called_once_with(
        "template excerpt for truncation",
        "corpus for truncation",
        expected_truncated_images,
        "notes for truncation",
        [],
        request_id_arg_val,
    )
    mock_pipeline_instance.run.assert_called_once_with(
        "template excerpt for truncation",
        "corpus for truncation",
        expected_truncated_images,
        "notes for truncation",
        [],
        extra_styles="",
    )

    final_data_event = next(
        (item for item in streamed_data if item.get("type") == "data"), None
    )
    assert final_data_event is not None, "Final 'data' event not found in stream"
    expected_final_payload = {**base_ctx_trunc, **pipeline_section_map_trunc}
    assert final_data_event["payload"] == expected_final_payload
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_template_load_failure_refactored(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,
    mock_settings,
    mock_uuid4,
    client: TestClient,
    patched_temp_dir,
):
    mock_validate_and_extract_files.return_value = ("Corpus", [])
    expected_error_detail = "Template loading failed for excerpt"
    mock_load_template_excerpt.side_effect = HTTPException(
        status_code=500, detail=expected_error_detail
    )

    file_tuple = ("test.pdf", b"dummy", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Test notes", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)
    assert response.status_code == 200

    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    assert len(streamed_data) > 0
    found_error = False
    for item in streamed_data:
        if item.get("type") == "error" and item.get("message") == expected_error_detail:
            found_error = True
            break
    assert (
        found_error
    ), f"Expected error message '{expected_error_detail}' not found in stream: {streamed_data}"

    mock_validate_and_extract_files.assert_called_once()
    _, _, request_id_arg = mock_validate_and_extract_files.call_args[0]
    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg
    )
    mock_retrieve_similar_cases.assert_not_called()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_validation_failure_refactored(
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    expected_error_detail = "Invalid file type"
    mock_validate_and_extract_files.side_effect = HTTPException(
        status_code=400, detail=expected_error_detail
    )

    file_tuple = ("invalid.txt", b"dummy content", "text/plain")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Test notes", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    found_error = any(
        item.get("type") == "error" and item.get("message") == expected_error_detail
        for item in streamed_data
    )
    assert (
        found_error
    ), f"Expected error message '{expected_error_detail}' not found in stream: {streamed_data}"

    mock_validate_and_extract_files.assert_called_once()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_rag_error_refactored(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,
    mock_settings,
    mock_uuid4,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template_rag_error.docx"
    mock_validate_and_extract_files.return_value = ("Corpus for RAG error", [])
    mock_load_template_excerpt.return_value = "Template for RAG error"
    expected_error_detail = "RAG processing failed: RAG service failed"
    mock_retrieve_similar_cases.side_effect = HTTPException(
        status_code=500, detail=expected_error_detail
    )

    file_tuple = ("test.pdf", b"dummy", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Notes for RAG error", "use_rag": "true"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    found_error = any(
        item.get("type") == "error" and item.get("message") == expected_error_detail
        for item in streamed_data
    )
    assert (
        found_error
    ), f"Expected error message '{expected_error_detail}' not found in stream: {streamed_data}"

    mock_validate_and_extract_files.assert_called_once()
    _, _, request_id_arg_val = mock_validate_and_extract_files.call_args[0]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg_val
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Corpus for RAG error", True, request_id_arg_val
    )
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_llm_error_refactored(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,
    mock_settings,
    mock_uuid4,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template_llm_error.docx"
    mock_validate_and_extract_files.return_value = ("Corpus for LLM error", [])
    mock_load_template_excerpt.return_value = "Template for LLM error"
    mock_retrieve_similar_cases.return_value = []
    expected_error_detail = "LLM processing for base fields failed: LLM service errored"
    mock_extract_base_context.side_effect = HTTPException(
        status_code=500, detail=expected_error_detail
    )

    file_tuple = ("test.pdf", b"dummy", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Notes for LLM error", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    found_error = any(
        item.get("type") == "error" and item.get("message") == expected_error_detail
        for item in streamed_data
    )
    assert (
        found_error
    ), f"Expected error message '{expected_error_detail}' not found in stream: {streamed_data}"

    mock_validate_and_extract_files.assert_called_once()
    _, _, request_id_arg_val = mock_validate_and_extract_files.call_args[0]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg_val
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Corpus for LLM error", False, request_id_arg_val
    )
    mock_extract_base_context.assert_called_once_with(
        "Template for LLM error",
        "Corpus for LLM error",
        [],
        "Notes for LLM error",
        [],
        request_id_arg_val,
    )
    MockPipelineService.return_value.run.assert_not_called()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_pipeline_error_refactored(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,
    mock_settings,
    mock_uuid4,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template_pipeline_error.docx"
    mock_validate_and_extract_files.return_value = ("Corpus for pipeline error", [])
    mock_load_template_excerpt.return_value = "Template for pipeline error"
    mock_retrieve_similar_cases.return_value = []
    mock_extract_base_context.return_value = {"base": "context"}

    pipeline_error_message = "Simulated pipeline failure"
    # This is the message the _stream_report_generation_logic will yield
    expected_stream_error_message = (
        f"Pipeline processing error: {pipeline_error_message}"
    )

    mock_pipeline_instance = MockPipelineService.return_value

    async def mock_pipeline_run_gen_raises_error_sideffect(
        *args, **kwargs
    ):  # Ensure it accepts args
        await asyncio.sleep(0)  # Ensures it's an async generator
        raise PipelineError(pipeline_error_message)
        yield  # Unreachable, but makes it a generator syntax-wise

    mock_pipeline_instance.run = MagicMock(
        side_effect=mock_pipeline_run_gen_raises_error_sideffect
    )

    file_tuple = ("test.pdf", b"dummy", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Notes for pipeline error", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    found_error = any(
        item.get("type") == "error"
        and item.get("message", "") == expected_stream_error_message
        for item in streamed_data
    )
    assert (
        found_error
    ), f"Expected error message containing '{expected_stream_error_message}' not found in stream: {streamed_data}"

    mock_validate_and_extract_files.assert_called_once()
    _, _, request_id_arg_val = mock_validate_and_extract_files.call_args[0]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg_val
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Corpus for pipeline error", False, request_id_arg_val
    )
    mock_extract_base_context.assert_called_once_with(
        "Template for pipeline error",
        "Corpus for pipeline error",
        [],
        "Notes for pipeline error",
        [],
        request_id_arg_val,
    )
    mock_pipeline_instance.run.assert_called_once_with(
        "Template for pipeline error",
        "Corpus for pipeline error",
        [],
        "Notes for pipeline error",
        [],
        extra_styles="",
    )
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_generic_unexpected_error(
    mock_validate_and_extract_files,
    client: TestClient,
    patched_temp_dir,
):
    generic_error_message = "A very generic unexpected error!"
    mock_validate_and_extract_files.side_effect = Exception(generic_error_message)
    expected_stream_error_message = (
        f"An unexpected server error occurred: {generic_error_message}"
    )

    file_tuple = ("test.pdf", b"dummy", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Test notes", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    found_error = any(
        item.get("type") == "error"
        and item.get("message", "") == expected_stream_error_message
        for item in streamed_data
    )
    assert (
        found_error
    ), f"Expected error message containing '{expected_stream_error_message}' not found in stream: {streamed_data}"

    mock_validate_and_extract_files.assert_called_once()
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="testrequestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_simulated_doc_builder_as_pipeline_stream_error(
    mock_validate_and_extract_files,
    mock_load_template_excerpt,
    mock_retrieve_similar_cases,
    mock_extract_base_context,
    MockPipelineService,
    mock_settings,
    mock_uuid4,
    client: TestClient,
    patched_temp_dir,
):
    mock_settings.template_path = "mock/template_doc_build_error.docx"
    mock_validate_and_extract_files.return_value = ("Corpus for doc build error", [])
    mock_load_template_excerpt.return_value = "Template for doc build error"
    mock_retrieve_similar_cases.return_value = []
    mock_extract_base_context.return_value = {"base": "context for doc build"}

    expected_error_detail = (
        "Simulated document construction failure within pipeline stream"
    )

    mock_pipeline_instance = MockPipelineService.return_value

    async def mock_pipeline_run_gen_internal_error_sideffect(
        *args, **kwargs
    ):  # Ensure it accepts args
        yield json.dumps({"type": "status", "message": "Pipeline running..."})
        await asyncio.sleep(0)
        yield json.dumps({"type": "error", "message": expected_error_detail})

    mock_pipeline_instance.run = MagicMock(
        side_effect=mock_pipeline_run_gen_internal_error_sideffect
    )

    file_tuple = ("test.pdf", b"dummy", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": "Notes for doc build error", "use_rag": "false"}

    response = client.post("/generate", files=files_for_request, data=form_data)

    assert response.status_code == 200
    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    found_error = any(
        item.get("type") == "error" and item.get("message") == expected_error_detail
        for item in streamed_data
    )
    assert (
        found_error
    ), f"Expected error message '{expected_error_detail}' not found in stream: {streamed_data}"

    mock_validate_and_extract_files.assert_called_once()
    _, _, request_id_arg_val = mock_validate_and_extract_files.call_args[0]

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), request_id_arg_val
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        "Corpus for doc build error", False, request_id_arg_val
    )
    mock_extract_base_context.assert_called_once_with(
        "Template for doc build error",
        "Corpus for doc build error",
        [],
        "Notes for doc build error",
        [],
        request_id_arg_val,
    )
    mock_pipeline_instance.run.assert_called_once_with(
        "Template for doc build error",
        "Corpus for doc build error",
        [],
        "Notes for doc build error",
        [],
        extra_styles="",
    )
    patched_temp_dir.assert_called_once()


# --- BEGINNING OF NEW TESTS FOR FEATURE 1 ---


@pytest.mark.asyncio
@patch("app.api.routes.uuid4")  # Ensure this is the generic patch
@patch("app.api.routes.settings")
@patch("app.api.routes.ClarificationService.identify_missing_fields")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_clarification_needed(
    mock_validate_and_extract_files: AsyncMock,
    mock_load_template_excerpt: AsyncMock,
    mock_retrieve_similar_cases: AsyncMock,
    mock_extract_base_context: AsyncMock,
    mock_identify_missing_fields: MagicMock,
    mock_settings: MagicMock,
    mock_uuid4: MagicMock,  # mock_uuid4 is the patcher object
    client: TestClient,
    patched_temp_dir: MagicMock,
):
    """Test /generate endpoint when clarification is needed."""
    # 1. Setup Mocks
    mock_uuid4.return_value.__str__.return_value = "clarifytestid01"  # Correct setup
    mock_settings.template_path = "mock/template.docx"
    mock_settings.CRITICAL_FIELDS_FOR_CLARIFICATION = {
        "polizza": {"label": "Numero Polizza", "question": "Numero polizza?"},
        "data_danno": {"label": "Data Danno", "question": "Data danno?"},
    }
    mock_corpus = "Test corpus for clarification"
    mock_imgs_tokens = ["img1.jpg"]
    mock_notes = "Some notes"
    mock_use_rag = False
    mock_similar_cases: list = []
    mock_validate_and_extract_files.return_value = (mock_corpus, mock_imgs_tokens)
    mock_load_template_excerpt.return_value = "Test template excerpt"
    mock_retrieve_similar_cases.return_value = mock_similar_cases
    initial_base_ctx_dict = {
        "client": "Test Client",
        "polizza": None,
        "data_danno": "2023-01-01",
    }
    mock_extract_base_context.return_value = initial_base_ctx_dict
    expected_missing_fields = [
        {"key": "polizza", "label": "Numero Polizza", "question": "Numero polizza?"}
    ]
    mock_identify_missing_fields.return_value = expected_missing_fields
    file_tuple = ("doc.pdf", b"dummy content", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {
        "notes": mock_notes,
        "use_rag": "false" if not mock_use_rag else "true",
    }
    response = client.post("/generate", files=files_for_request, data=form_data)
    assert response.status_code == 200
    streamed_data = [json.loads(line) for line in response.iter_lines() if line]
    clarification_event = next(
        (item for item in streamed_data if item.get("type") == "clarification_needed"),
        None,
    )
    assert clarification_event is not None, "'clarification_needed' event not found"
    assert clarification_event["missing_fields"] == expected_missing_fields
    expected_artifacts = {
        "original_corpus": mock_corpus,
        "image_tokens": mock_imgs_tokens,
        "notes": mock_notes,
        "use_rag": mock_use_rag,
        "similar_cases_retrieved": mock_similar_cases,
        "initial_llm_base_fields": initial_base_ctx_dict,
    }
    assert clarification_event["request_artifacts"] == expected_artifacts
    mock_validate_and_extract_files.assert_called_once()
    assert (
        mock_validate_and_extract_files.call_args[0][2] == "clarifytestid01"
    )  # Correct assertion
    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), "clarifytestid01"
    )
    mock_retrieve_similar_cases.assert_called_once_with(
        mock_corpus, mock_use_rag, "clarifytestid01"
    )
    mock_extract_base_context.assert_called_once_with(
        "Test template excerpt",
        mock_corpus,
        mock_imgs_tokens,
        mock_notes,
        mock_similar_cases,
        "clarifytestid01",
    )
    mock_identify_missing_fields.assert_called_once_with(
        initial_base_ctx_dict, mock_settings.CRITICAL_FIELDS_FOR_CLARIFICATION
    )
    patched_temp_dir.assert_called_once()


@pytest.mark.asyncio
@patch("app.api.routes.uuid4")  # MODIFIED
@patch("app.api.routes.settings")
@patch("app.api.routes.ClarificationService.identify_missing_fields")
@patch("app.api.routes.PipelineService")
@patch("app.api.routes._extract_base_context", new_callable=AsyncMock)
@patch("app.api.routes._retrieve_similar_cases", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
@patch("app.api.routes._validate_and_extract_files", new_callable=AsyncMock)
async def test_generate_endpoint_no_clarification_proceeds_to_data(
    mock_validate_and_extract_files: AsyncMock,
    mock_load_template_excerpt: AsyncMock,
    mock_retrieve_similar_cases: AsyncMock,
    mock_extract_base_context: AsyncMock,
    MockPipelineService: MagicMock,
    mock_identify_missing_fields: MagicMock,
    mock_settings: MagicMock,
    mock_uuid4: MagicMock,  # This is the patcher
    client: TestClient,
    patched_temp_dir: MagicMock,
):
    """Test /generate when no clarification is needed, proceeds to yield data."""
    mock_uuid4.return_value.__str__.return_value = "noclarifytestid02"  # MODIFIED setup
    mock_settings.template_path = "mock/template_no_clarify.docx"
    mock_settings.CRITICAL_FIELDS_FOR_CLARIFICATION = {
        "polizza": {"label": "Numero Polizza", "question": "Numero polizza?"}
    }
    mock_corpus = "Test corpus no clarification"
    mock_imgs_tokens = ["img_no_clarify.jpg"]
    mock_notes = "Some notes no clarify"
    mock_use_rag = True
    mock_similar_cases = [{"case_id": "sim1"}]
    mock_validate_and_extract_files.return_value = (mock_corpus, mock_imgs_tokens)
    mock_load_template_excerpt.return_value = "Test template excerpt no clarify"
    mock_retrieve_similar_cases.return_value = mock_similar_cases
    initial_base_ctx_dict = {"client": "Test Client", "polizza": "XYZ123"}
    mock_extract_base_context.return_value = initial_base_ctx_dict
    mock_identify_missing_fields.return_value = []
    mock_pipeline_instance = MockPipelineService.return_value
    pipeline_section_map = {"sectionA": "Content A"}

    async def mock_pipeline_run_gen_success(*args, **kwargs):
        yield json.dumps({"type": "status", "message": "Pipeline processing..."})
        await asyncio.sleep(0)
        yield json.dumps({"type": "data", "payload": pipeline_section_map})

    mock_pipeline_instance.run = MagicMock(side_effect=mock_pipeline_run_gen_success)
    file_tuple = ("doc_no_clarify.pdf", b"dummy content nc", "application/pdf")
    files_for_request = [("files", file_tuple)]
    form_data = {"notes": mock_notes, "use_rag": "true" if mock_use_rag else "false"}
    response = client.post("/generate", files=files_for_request, data=form_data)
    assert response.status_code == 200
    streamed_data = [json.loads(line) for line in response.iter_lines() if line]
    data_event = next(
        (item for item in streamed_data if item.get("type") == "data"), None
    )
    assert not any(
        item.get("type") == "clarification_needed" for item in streamed_data
    ), "Clarification event found unexpectedly"
    assert data_event is not None, "'data' event not found"
    expected_final_ctx = {**initial_base_ctx_dict, **pipeline_section_map}
    assert data_event["payload"] == expected_final_ctx
    mock_identify_missing_fields.assert_called_once_with(
        initial_base_ctx_dict, mock_settings.CRITICAL_FIELDS_FOR_CLARIFICATION
    )
    # Assert correct request_id was used in downstream calls if necessary, e.g.:
    # mock_load_template_excerpt.assert_called_once_with(str(mock_settings.template_path), "noclarifytestid02")
    mock_pipeline_instance.run.assert_called_once()
    patched_temp_dir.assert_called_once()


# --- END OF NEW TESTS FOR FEATURE 1 ---


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="genwithclarifytestid"))
@patch("app.api.routes.settings")
@patch(
    "app.api.routes._generate_and_stream_docx", new_callable=AsyncMock
)  # Mock the final docx generation
@patch(
    "app.api.routes._run_processing_pipeline", new_callable=AsyncMock
)  # Mock the pipeline run
@patch(
    "app.api.routes._load_template_excerpt", new_callable=AsyncMock
)  # Mock template loading
async def test_generate_with_clarifications_success(
    mock_load_template_excerpt: AsyncMock,
    mock_run_processing_pipeline: AsyncMock,
    mock_generate_and_stream_docx: AsyncMock,
    mock_settings: MagicMock,
    mock_uuid4: MagicMock,
    client: TestClient,
):
    """Test POST /api/generate-with-clarifications successful path."""
    mock_uuid4.return_value.__str__.return_value = "genwithclarifytestid03"
    mock_settings.template_path = "mock/template_for_clarify_gen.docx"
    mock_load_template_excerpt.return_value = "Excerpt for clarified generation"
    mock_section_map = {"clarified_section": "This is now clarified content"}
    mock_run_processing_pipeline.return_value = mock_section_map

    # MODIFIED: Return a real StreamingResponse
    mock_generate_and_stream_docx.return_value = StreamingResponse(
        iter([b"dummy docx bytes for test"])
    )

    initial_base_fields = {
        "client": "Original Client",
        "polizza": None,  # Was missing
        "data_danno": "2023-01-01",
    }
    user_clarifications = {
        "polizza": "POL98765",  # User provided this
        "another_field_clarified": "newValue",
    }
    request_artifacts_payload = {
        "original_corpus": "Original corpus data",
        "image_tokens": ["img1.png"],
        "notes": "Original notes",
        "use_rag": False,
        "similar_cases_retrieved": [],
        "initial_llm_base_fields": initial_base_fields,  # This will be converted to ReportContext by Pydantic
    }
    payload = {
        "clarifications": user_clarifications,
        "request_artifacts": request_artifacts_payload,
    }

    # 2. Make Request
    response = client.post("/generate-with-clarifications", json=payload)

    # 3. Assert Response and Mock Calls
    assert (
        response.status_code == 200
    )  # Should be the status_code from mock_docx_response if it's a real response obj
    # If _generate_and_stream_docx returns the raw iter bytes, TestClient handles it.

    mock_load_template_excerpt.assert_called_once_with(
        str(mock_settings.template_path), "genwithclarifytestid03"
    )

    mock_run_processing_pipeline.assert_called_once_with(
        template_excerpt="Excerpt for clarified generation",
        corpus=request_artifacts_payload["original_corpus"],
        imgs=request_artifacts_payload["image_tokens"],
        notes=request_artifacts_payload["notes"],
        similar_cases=request_artifacts_payload["similar_cases_retrieved"],
        request_id="genwithclarifytestid03",
    )

    expected_merged_base_ctx = {
        "client": "Original Client",
        "polizza": "POL98765",  # Updated
        "data_danno": "2023-01-01",
        "another_field_clarified": "newValue",  # Added
    }
    expected_final_ctx = {**expected_merged_base_ctx, **mock_section_map}

    mock_generate_and_stream_docx.assert_called_once_with(
        template_path=str(mock_settings.template_path),
        final_context=expected_final_ctx,
        request_id="genwithclarifytestid03",
    )


@pytest.mark.asyncio
@patch("app.api.routes.uuid4")  # MODIFIED
@patch("app.api.routes.settings")
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
@patch("app.api.routes._run_processing_pipeline", new_callable=AsyncMock)
@patch("app.api.routes._load_template_excerpt", new_callable=AsyncMock)
async def test_generate_with_clarifications_pipeline_error(
    mock_load_template_excerpt: AsyncMock,
    mock_run_processing_pipeline: AsyncMock,
    mock_generate_and_stream_docx: AsyncMock,
    mock_settings: MagicMock,
    mock_uuid4: MagicMock,
    client: TestClient,
):
    """Test POST /api/generate-with-clarifications when pipeline errors."""
    mock_uuid4.return_value.__str__.return_value = (
        "gwc_pipeline_error_id04"  # MODIFIED setup
    )
    mock_settings.template_path = "mock/template.docx"
    mock_load_template_excerpt.return_value = "Some Excerpt"
    pipeline_error_msg = "Pipeline failed during clarification processing"
    mock_run_processing_pipeline.side_effect = PipelineError(pipeline_error_msg)
    payload = {
        "clarifications": {"polizza": "clarified"},
        "request_artifacts": {
            "original_corpus": "corpus",
            "image_tokens": [],
            "notes": "notes",
            "use_rag": False,
            "similar_cases_retrieved": [],
            "initial_llm_base_fields": {"client": "Test"},
        },
    }
    response = client.post("/generate-with-clarifications", json=payload)
    assert response.status_code == 500
    assert pipeline_error_msg in response.json()["detail"]
    mock_generate_and_stream_docx.assert_not_called()


# --- END OF NEW TESTS FOR FEATURE 1 ---


@pytest.mark.asyncio
@patch("app.api.routes.uuid4", return_value=MagicMock(hex="finalizetestid"))
@patch("app.api.routes.settings")
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
async def test_finalize_report_success(
    mock_generate_and_stream_docx: AsyncMock,
    mock_settings: MagicMock,
    mock_uuid4: MagicMock,
    client: TestClient,
):
    """Test POST /api/finalize-report successful path."""
    mock_uuid4.return_value.__str__.return_value = "finalizetestid05"
    mock_settings.template_path = "mock/template_for_finalize.docx"

    # MODIFIED: Return a real StreamingResponse
    mock_generate_and_stream_docx.return_value = StreamingResponse(
        iter([b"dummy docx content for finalize test"])
    )

    final_ctx_payload = {
        "client": "Final Client",
        "polizza": "POLFINAL123",
        "dinamica_eventi": "Final dynamics",
    }
    response = client.post("/finalize-report", json=final_ctx_payload)

    assert response.status_code == 200

    mock_generate_and_stream_docx.assert_called_once_with(
        template_path=str(mock_settings.template_path),
        final_context=final_ctx_payload,
        request_id="finalizetestid05",
    )


@pytest.mark.asyncio
@patch("app.api.routes.uuid4")  # MODIFIED
@patch("app.api.routes.settings")
@patch("app.api.routes._generate_and_stream_docx", new_callable=AsyncMock)
async def test_finalize_report_docbuilder_error(
    mock_generate_and_stream_docx: AsyncMock,
    mock_settings: MagicMock,
    mock_uuid4: MagicMock,  # This is the patcher
    client: TestClient,
):
    """Test POST /api/finalize-report when _generate_and_stream_docx errors."""
    mock_uuid4.return_value.__str__.return_value = (
        "finalize_docbuild_error_id06"  # MODIFIED setup
    )
    mock_settings.template_path = "mock/template.docx"
    docbuilder_error_msg = "Failed to inject final document"
    mock_generate_and_stream_docx.side_effect = DocBuilderError(docbuilder_error_msg)
    final_ctx_payload = {"client": "Test Client", "polizza": "ErrorCase"}
    response = client.post("/finalize-report", json=final_ctx_payload)
    assert response.status_code == 500
    assert docbuilder_error_msg in response.json()["detail"]


# --- END OF NEW TESTS FOR FEATURE 1 ---


# --- Tests for Generic Exception Handling in Helper Functions ---


@pytest.mark.asyncio
@patch("app.api.routes.Document")  # Assuming Document is from python-docx
@patch("app.api.routes.logger")
async def test_load_template_excerpt_generic_exception(
    mock_logger: MagicMock,
    mock_docx_document: MagicMock,
    # client: TestClient # Not needed for this unit test
):
    """Test _load_template_excerpt generic exception handling."""
    from app.api.routes import _load_template_excerpt  # Local import for clarity

    mock_docx_document.side_effect = Exception("Generic docx loading error")
    template_path = "dummy/path.docx"
    request_id = "test_req_id_load_template_generic"

    with pytest.raises(HTTPException) as exc_info:
        await _load_template_excerpt(template_path, request_id)

    assert exc_info.value.status_code == 500
    assert "Error loading template excerpt." in str(exc_info.value.detail)
    mock_logger.error.assert_called_once_with(
        "[%s] Failed to load template for excerpt: %s",  # Actual format string
        request_id,  # First %s arg
        "Generic docx loading error",  # Second %s arg
        exc_info=True,
    )


@pytest.mark.asyncio
@patch("app.api.routes.RAGService")
@patch("app.api.routes.logger")
async def test_retrieve_similar_cases_generic_exception(
    mock_logger: MagicMock,
    mock_rag_service: MagicMock,
):
    """Test _retrieve_similar_cases generic exception handling."""
    from app.api.routes import _retrieve_similar_cases  # Local import for clarity

    mock_rag_instance = mock_rag_service.return_value
    mock_rag_instance.retrieve.side_effect = Exception("Generic RAG service error")
    corpus = "test corpus"
    use_rag = True
    request_id = "test_req_id_rag_generic"

    with pytest.raises(HTTPException) as exc_info:
        await _retrieve_similar_cases(corpus, use_rag, request_id)

    assert exc_info.value.status_code == 500
    assert "An unexpected error occurred while retrieving similar cases." in str(
        exc_info.value.detail
    )
    mock_logger.error.assert_called_once_with(
        "[%s] RAG retrieval failed unexpectedly: %s",  # Actual format string
        request_id,  # First %s arg
        "Generic RAG service error",  # Second %s arg
        exc_info=True,
    )


@pytest.mark.asyncio
@patch(
    "app.api.routes.PipelineService"
)  # Assuming PipelineService is used as in other tests
@patch("app.api.routes.logger")
async def test_run_processing_pipeline_generic_exception_in_run(
    mock_logger: MagicMock,
    MockPipelineService: MagicMock,
):
    """Test _run_processing_pipeline generic exception during pipeline.run()."""
    from app.api.routes import _run_processing_pipeline  # Local import
    from app.services.pipeline import PipelineError  # Local import for PipelineError

    mock_pipeline_instance = MockPipelineService.return_value

    async def mock_run_raises_generic_exception(*args, **kwargs):
        raise Exception("Generic error during pipeline run")
        yield  # To make it an async generator

    mock_pipeline_instance.run = MagicMock(
        side_effect=mock_run_raises_generic_exception
    )

    request_id = "test_req_id_pipeline_generic_run"

    with pytest.raises(PipelineError) as exc_info:
        await _run_processing_pipeline(
            template_excerpt="excerpt",
            corpus="corpus",
            imgs=[],
            notes="notes",
            similar_cases=[],
            request_id=request_id,
        )

    assert (
        "An unexpected error occurred in the report generation pipeline: Generic error during pipeline run"
        in str(exc_info.value)
    )
    mock_logger.error.assert_called_once_with(
        "[%s] Unexpected pipeline processing error: %s",  # Actual format string
        request_id,  # First %s arg
        "Generic error during pipeline run",  # Second %s arg
        exc_info=True,
    )


@pytest.mark.asyncio
@patch("app.api.routes.json.loads")  # Changed
@patch("app.api.routes.PipelineService")
@patch("app.api.routes.logger")
async def test_run_processing_pipeline_generic_exception_json_loads(
    mock_logger: MagicMock,
    MockPipelineService: MagicMock,
    mock_json_loads: MagicMock,  # Changed
):
    """Test _run_processing_pipeline generic exception during json.loads()."""
    from app.api.routes import _run_processing_pipeline  # Local import
    from app.services.pipeline import PipelineError  # Local import for PipelineError

    mock_pipeline_instance = MockPipelineService.return_value

    async def mock_run_yields_valid_json_then_bad_call(*args, **kwargs):
        yield """{\"type\": \"status\", \"message\": \"processing...\"}"""
        # Next call to json.loads will be mocked to fail
        yield """{\"type\": \"data\", \"payload\": {}}"""

    mock_pipeline_instance.run = MagicMock(
        side_effect=mock_run_yields_valid_json_then_bad_call
    )
    # First call to json.loads is fine, second one raises generic Exception
    mock_json_loads.side_effect = [
        json.loads("""{\"type\": \"status\", \"message\": \"processing...\"}"""),
        Exception("Generic JSON load error"),
    ]

    request_id = "test_req_id_pipeline_generic_json"

    with pytest.raises(PipelineError) as exc_info:
        await _run_processing_pipeline(
            template_excerpt="excerpt",
            corpus="corpus",
            imgs=[],
            notes="notes",
            similar_cases=[],
            request_id=request_id,
        )

    assert (
        "An unexpected error occurred in the report generation pipeline: Generic JSON load error"
        in str(exc_info.value)
    )
    # Assuming the generic exception in json.loads is caught by the outer generic exception handler in _run_processing_pipeline
    mock_logger.error.assert_called_once_with(
        "[%s] Unexpected pipeline processing error: %s",  # Actual format string
        request_id,  # First %s arg
        "Generic JSON load error",  # Second %s arg, from the Exception caught
        exc_info=True,
    )


@pytest.mark.asyncio
@patch("app.api.routes.inject")
@patch("app.api.routes.json")
@patch("app.api.routes.logger")
async def test_generate_and_stream_docx_generic_exception_inject(
    mock_logger: MagicMock,
    mock_json_dumps: MagicMock,
    mock_inject: MagicMock,
):
    """Test _generate_and_stream_docx generic exception from inject()."""
    from app.api.routes import _generate_and_stream_docx

    mock_inject.side_effect = Exception("Generic inject error")
    template_path = "dummy/template.docx"
    final_context = {"key": "value"}
    request_id = "test_req_id_docx_generic_inject"

    with pytest.raises(HTTPException) as exc_info:
        await _generate_and_stream_docx(
            template_path, final_context, request_id
        )  # Changed from async for

    assert exc_info.value.status_code == 500
    assert "An unexpected error occurred while generating the DOCX document." in str(
        exc_info.value.detail
    )
    mock_logger.error.assert_called_once_with(
        "[%s] Failed to generate final document: %s",  # Actual format string
        request_id,  # First %s arg
        "Generic inject error",  # Second %s arg
        exc_info=True,
    )


@pytest.mark.asyncio
@patch("app.api.routes.inject")
@patch("app.api.routes.json")
@patch("app.api.routes.logger")
async def test_generate_and_stream_docx_generic_exception_json_dumps(
    mock_logger: MagicMock,
    mock_json_module: MagicMock,
    mock_inject: MagicMock,
):
    """Test _generate_and_stream_docx generic exception from json.dumps()."""
    from app.api.routes import _generate_and_stream_docx

    mock_inject.return_value = MagicMock()
    mock_json_module.dumps.side_effect = Exception("Generic json.dumps error")

    template_path = "dummy/template.docx"
    final_context = {"key": "value"}
    request_id = "test_req_id_docx_generic_json_dumps"

    with pytest.raises(HTTPException) as exc_info:
        await _generate_and_stream_docx(
            template_path, final_context, request_id
        )  # Changed from async for

    assert exc_info.value.status_code == 500
    assert "An unexpected error occurred while generating the DOCX document." in str(
        exc_info.value.detail
    )
    mock_logger.error.assert_called_once_with(
        "[%s] Failed to generate final document: %s",  # Actual format string
        request_id,  # First %s arg
        "Generic json.dumps error",  # Second %s arg
        exc_info=True,
    )


# --- END of Tests for Generic Exception Handling ---
