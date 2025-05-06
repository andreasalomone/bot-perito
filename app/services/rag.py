# app/services/rag.py
import os, asyncio, async_lru
from typing import List, Dict
from sentence_transformers import SentenceTransformer
from supabase import create_client

class RAGService:
    """Singleton KISS per retrieval semantico."""
    _instance: "RAGService" | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_ANON_KEY"]          # solo lettura
        self.sb = create_client(url, key)
        self.model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

    # cache locale degli embedding per richieste ripetute
    @async_lru.alru_cache(maxsize=128)
    async def _embed_async(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.model.encode, text)

    async def retrieve(self, text: str, k: int = 3) -> List[Dict]:
        """Ritorna lista di dizionari: id, title, snippet."""
        emb = await self._embed_async(text)
        rows = (
            self.sb.rpc(
                "match_reference_reports",
                {"query_embedding": emb, "k": k}
            ).execute()
            .data
        )
        return rows or []