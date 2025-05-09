import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_generate_full_happy_path(monkeypatch):
    # Set API key
    monkeypatch.setattr(settings, "api_key", "secret", raising=False)

    # Skip file validation
    async def noop_validate_upload(file, request_id):
        return None

    monkeypatch.setattr("app.api.routes.validate_upload", noop_validate_upload)

    # Stub extraction functions
    async def fake_extract_texts(files, request_id):
        return ["text1"], ["img_token"]

    monkeypatch.setattr("app.api.routes.extract_texts", fake_extract_texts)

    async def fake_process_images(imgs, request_id):
        return []

    monkeypatch.setattr("app.api.routes.process_images", fake_process_images)
    # Stub guard_corpus to return original corpus
    monkeypatch.setattr("app.api.routes.guard_corpus", lambda x: x)

    # Stub Document to provide template excerpt
    class FakeTemplate:
        def __init__(self, path):
            # Provide minimal paragraphs excerpt
            Paragraph = type("Paragraph", (), {"text": "Ex"})
            self.paragraphs = [Paragraph()]

    monkeypatch.setattr("app.api.routes.Document", FakeTemplate)
    # Stub build_prompt to return small prompt
    monkeypatch.setattr("app.api.routes.build_prompt", lambda *args, **kwargs: "prompt")
    # Stub LLM and JSON extraction
    base_json = json.dumps(
        {
            "client": "C",
            "client_address1": "",
            "client_address2": "",
            "date": "D",
            "vs_rif": "",
            "rif_broker": "",
            "polizza": "",
            "ns_rif": "",
            "assicurato": "",
            "indirizzo_ass1": "",
            "indirizzo_ass2": "",
            "luogo": "",
            "data_danno": "",
            "cause": "",
            "data_incarico": "",
            "merce": "",
            "peso_merce": "",
            "valore_merce": "",
            "data_intervento": "",
            "dinamica_eventi": "dyn",
            "accertamenti": "acc",
            "quantificazione": "quant",
            "commento": "comm",
            "allegati": "",
        }
    )
    monkeypatch.setattr("app.api.routes.call_llm", lambda prompt: base_json)

    # Use actual extract_json or stub if necessary
    # Stub pipeline service
    class FakePipeline:
        async def run(self, tpl, corpus, imgs, notes, similar_cases, extra_styles):
            return {
                "dinamica_eventi": "dyn",
                "accertamenti": "acc",
                "quantificazione": "quant",
                "commento": "comm",
            }

    monkeypatch.setattr("app.api.routes.PipelineService", lambda: FakePipeline())
    # Stub inject to return known bytes
    monkeypatch.setattr("app.api.routes.inject", lambda tpl_path, payload: b"PK1234")
    client = TestClient(app)
    # Call generate endpoint with dummy file
    response = client.post(
        "/generate",
        files=[("files", ("dummy.pdf", b"dummy", "application/pdf"))],
        data={"notes": "", "use_rag": "false"},
        headers={"X-API-Key": "secret"},
    )
    assert response.status_code == 200
    # StreamingResponse returns raw bytes
    assert response.content == b"PK1234"
    assert "attachment; filename" in response.headers.get("content-disposition", "")
