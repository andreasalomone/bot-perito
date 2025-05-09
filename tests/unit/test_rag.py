import pytest

from app.services.rag import RAGError, RAGService

pytestmark = pytest.mark.asyncio


async def test_missing_env(monkeypatch):
    # Ensure environment variables are removed
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    # Reset singleton
    RAGService._instance = None  # type: ignore
    with pytest.raises(RAGError) as exc:
        RAGService()
    assert "Missing required environment variables" in str(exc.value)


async def test_retrieve_success(monkeypatch):
    # Setup environment and dummy client
    monkeypatch.setenv("SUPABASE_URL", "url")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "key")

    rows = [{"id": 1, "title": "Title", "snippet": "Snip"}]

    class DummyClient:
        def rpc(self, name, params):
            return type(
                "Resp",
                (),
                {"execute": lambda self=None: type("R", (), {"data": rows})()},
            )()

    monkeypatch.setattr(
        "app.services.rag.create_client", lambda url, key: DummyClient(), raising=True
    )
    # Monkeypatch embed to a simple embedding list
    monkeypatch.setattr("app.services.rag.embed", lambda text: [0.1, 0.2], raising=True)

    # Reset singleton
    RAGService._instance = None  # type: ignore
    service = RAGService()
    result = await service.retrieve("some text", k=3)
    assert result == rows


async def test_retrieve_client_uninitialized(monkeypatch):
    # Setup environment but force create_client to return None
    monkeypatch.setenv("SUPABASE_URL", "url")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "key")
    monkeypatch.setattr(
        "app.services.rag.create_client", lambda url, key: None, raising=True
    )

    # Reset singleton and initialize service
    RAGService._instance = None  # type: ignore
    service = RAGService()

    # Retrieval should fail due to uninitialized client
    with pytest.raises(RAGError) as exc:
        await service.retrieve("text")
    assert "Supabase client not initialized" in str(exc.value)
