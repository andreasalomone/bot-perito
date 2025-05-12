import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_generate_full_happy_path(monkeypatch):
    # If client fixture is not available in this e2e context, TestClient(app) will be used.
    # The client fixture from unit tests might handle dependency_overrides for verify_api_key.
    # For a pure E2E, we often let verify_api_key run, or mock it minimally here.

    # Set API key for the actual verify_api_key to use via settings
    monkeypatch.setattr(settings, "api_key", "secret")
    monkeypatch.setattr(settings, "template_path", "mock_template.docx")

    # Mock components called by app.api.routes.generate and its helpers
    async def noop_validate_upload(file, request_id):
        return None

    monkeypatch.setattr("app.core.validation.validate_upload", noop_validate_upload)

    async def fake_extract_texts(files, request_id):
        return ["text1"], ["img_token"]

    monkeypatch.setattr(
        "app.generation_logic.file_processing.extract_texts", fake_extract_texts
    )

    async def fake_process_images(imgs, request_id):
        return []

    monkeypatch.setattr(
        "app.generation_logic.file_processing.process_images", fake_process_images
    )

    monkeypatch.setattr("app.services.extractor.guard_corpus", lambda x: x)

    class FakeParagraph:
        def __init__(self, text="Ex"):
            self.text = text

    class FakeTemplate:
        def __init__(self, path):
            self.paragraphs = [FakeParagraph(f"Paragraph {i}") for i in range(8)]

    monkeypatch.setattr(
        "app.generation_logic.context_preparation.Document", FakeTemplate
    )

    monkeypatch.setattr(
        "app.services.llm.build_prompt", lambda *args, **kwargs: "prompt"
    )

    base_json_dict = {
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
        "dinamica_eventi": "dyn_base",
        "accertamenti": "acc_base",
        "quantificazione": "quant_base",
        "commento": "comm_base",
        "allegati": "",
    }
    base_json_str = json.dumps(base_json_dict)

    async def fake_call_llm(prompt):
        return base_json_str

    monkeypatch.setattr("app.services.llm.call_llm", fake_call_llm)

    monkeypatch.setattr(
        "app.services.llm.extract_json", lambda raw_json_string: base_json_dict
    )

    class FakeRAGService:
        async def retrieve(self, corpus, k):
            return []

    monkeypatch.setattr("app.services.rag.RAGService", lambda: FakeRAGService())

    # Updated FakePipeline mock
    class FakePipeline:
        async def run(self, tpl, corpus, imgs, notes, similar_cases, extra_styles):
            pipeline_payload = {
                "dinamica_eventi": "dyn_pipeline_stream",
                "accertamenti": "acc_pipeline_stream",
                "quantificazione": "quant_pipeline_stream",
                "commento": "comm_pipeline_stream",
            }
            yield json.dumps({"type": "status", "message": "Pipeline started"})
            yield json.dumps({"type": "data", "payload": pipeline_payload})

    monkeypatch.setattr("app.services.pipeline.PipelineService", lambda: FakePipeline())

    # Remove mock for app.api.routes.inject as it's not used by /generate stream
    # monkeypatch.setattr("app.api.routes.inject", lambda tpl_path, payload: b"PK1234")

    local_client = TestClient(app)

    response = local_client.post(
        "/generate",
        files=[("files", ("dummy.pdf", b"dummy content for file", "application/pdf"))],
        data={"notes": "some notes for the test", "use_rag": "false"},
        headers={"X-API-Key": "secret"},
    )

    if response.status_code != 200:
        print(f"E2E Test Failure Response ({response.status_code}):")
        try:
            print(json.dumps(response.json(), indent=2))
        except Exception:
            print(response.text)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson"

    streamed_data = []
    for line in response.iter_lines():
        if line:
            streamed_data.append(json.loads(line))

    final_data_event = None
    for item in streamed_data:
        if item.get("type") == "data" and "payload" in item:
            final_data_event = item
            break

    assert final_data_event is not None, "Final 'data' event not found in stream"

    # base_json_dict is defined earlier in the test
    expected_pipeline_payload = {
        "dinamica_eventi": "dyn_pipeline_stream",
        "accertamenti": "acc_pipeline_stream",
        "quantificazione": "quant_pipeline_stream",
        "commento": "comm_pipeline_stream",
    }
    expected_combined_context = {**base_json_dict, **expected_pipeline_payload}

    assert (
        final_data_event["payload"] == expected_combined_context
    ), f"Payload mismatch. Expected: {expected_combined_context}, Got: {final_data_event['payload']}"

    # Remove assertions for DOCX content and headers
    # assert response.content == b"PK1234"
    # content_disposition = response.headers.get("content-disposition", "").lower()
    # assert "attachment" in content_disposition
    # assert "filename=report.docx" in content_disposition
