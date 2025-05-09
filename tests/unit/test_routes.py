import asyncio  # Added for asyncio.sleep
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
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
