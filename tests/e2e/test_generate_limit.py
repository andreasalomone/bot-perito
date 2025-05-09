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
        return ([], [])  # (texts, imgs)

    monkeypatch.setattr("app.api.routes.extract_texts", mock_extract_texts)

    # Configure prompt size threshold small and stub build_prompt to exceed it
    monkeypatch.setattr(settings, "max_total_prompt_chars", 10, raising=False)
    monkeypatch.setattr(
        "app.services.llm.build_prompt", lambda *args, **kwargs: "X" * 11
    )
    client = TestClient(app)
    # Send minimal dummy file
    response = client.post(
        "/generate",
        files=[("files", ("dummy.pdf", b"dummy content", "application/pdf"))],
        data={"notes": "", "use_rag": "false"},
        headers={"X-API-Key": "secret"},
    )
    assert response.status_code == 413
    assert response.json() == {"error": "Prompt troppo grande o troppi allegati"}
