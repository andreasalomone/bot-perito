import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_generate_prompt_size_limit(monkeypatch):
    # Set API key in settings and header
    monkeypatch.setattr(settings, "api_key", "secret", raising=False)

    # Disable file validation
    async def noop_validate_upload(file, request_id):
        return None

    monkeypatch.setattr("app.api.routes.validate_upload", noop_validate_upload)

    # Mock extract_texts to avoid issues with dummy PDF content
    async def mock_extract_texts(files, request_id):
        # Return minimal corpus and no images to ensure prompt is mainly from build_prompt
        return ("tiny", [])  # (texts, imgs)

    monkeypatch.setattr("app.api.routes.extract_texts", mock_extract_texts)

    # Configure prompt size threshold small and stub build_prompt to exceed it
    monkeypatch.setattr(settings, "max_total_prompt_chars", 10, raising=False)
    # build_prompt is in app.services.llm, but _extract_base_context in routes calls it.
    # The HTTPException(413) is raised in _extract_base_context in routes.py
    # We need _extract_base_context to raise the error, or an earlier step like _load_template_excerpt
    # For this test, let's ensure _extract_base_context itself notices the large prompt from a mocked build_prompt
    # and raises the HTTPException(413)

    # Mock build_prompt within the llm service which is called by _extract_base_context
    monkeypatch.setattr(
        "app.services.llm.build_prompt", lambda *args, **kwargs: "X" * 11
    )

    # Also mock other preceding helper functions in routes.py to return minimal valid data
    async def mock_load_template_excerpt(*args, **kwargs):
        return "short excerpt"

    monkeypatch.setattr(
        "app.api.routes._load_template_excerpt", mock_load_template_excerpt
    )

    async def mock_retrieve_similar_cases(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.api.routes._retrieve_similar_cases", mock_retrieve_similar_cases
    )

    client = TestClient(app)
    response = client.post(
        "/generate",
        files=[("files", ("dummy.pdf", b"dummy content", "application/pdf"))],
        data={"notes": "", "use_rag": "false"},
        headers={"X-API-Key": settings.api_key},
    )
    assert response.status_code == 200  # Stream is 200 OK

    streamed_data = []
    for (
        line
    ) in response.iter_lines():  # TestClient supports iter_lines for streaming response
        if line:
            streamed_data.append(json.loads(line))

    expected_error_detail = "Prompt too large or too many attachments"
    found_error = any(
        item.get("type") == "error" and item.get("message") == expected_error_detail
        for item in streamed_data
    )
    assert (
        found_error
    ), f"Expected error message '{expected_error_detail}' not found in stream: {streamed_data}"
