import pytest

from app.services.rag import RAGService


class DummyClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        # Return object with execute method
        return type(
            "Resp", (), {"execute": lambda self=None: type("R", (), {"data": []})()}
        )()


@pytest.mark.asyncio
async def test_embed_async_caching(monkeypatch):
    # Setup env vars for Supabase
    monkeypatch.setenv("SUPABASE_URL", "url")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "key")
    # Monkeypatch client creation
    monkeypatch.setattr(
        "app.services.rag.create_client", lambda url, key: DummyClient(), raising=True
    )
    # Track embed calls
    call_count = {"n": 0}

    def fake_embed(text):
        call_count["n"] += 1
        return [0.1, 0.2]

    monkeypatch.setattr("app.services.rag.embed", fake_embed, raising=True)
    # Ensure new singleton
    RAGService._instance = None  # type: ignore
    service = RAGService()
    # First retrieval: embed called once
    await service.retrieve("text", k=1)
    # Second retrieval with same text: embed should not be called again
    await service.retrieve("text", k=1)
    assert call_count["n"] == 1
