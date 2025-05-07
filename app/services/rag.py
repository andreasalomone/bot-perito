from __future__ import annotations
import os, asyncio, async_lru, dotenv
from typing import List, Dict
from sentence_transformers import SentenceTransformer
from supabase import create_client

dotenv.load_dotenv()

class RAGService:
    """Singleton KISS per retrieval semantico."""
    _instance: "RAGService" | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        try:
            url = os.environ["SUPABASE_URL"]
            key = os.environ["SUPABASE_ANON_KEY"]          # solo lettura

            if not url or not key:
                print("Missing Supabase environment variables")
                raise ValueError("Missing required environment variables")

            self.sb = create_client(url, key)

            try:
                print("Loading SentenceTransformer model...")
                self.model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
                print("SentenceTransformer model loaded successfully")
            except Exception as model_error:
                print(f"Error loading SentenceTransformer model: {model_error}")
                raise

        except Exception as e:
            print(f"Error initializing RAGService: {e}")
            # Set default values to prevent attribute errors
            self.sb = None
            self.model = None

    # cache locale degli embedding per richieste ripetute
    @async_lru.alru_cache(maxsize=128)
    async def retrieve(self, text: str, k: int = 3) -> List[Dict]:
        """Ritorna lista di dizionari: id, title, snippet."""
        try:
            if self.model is None:
                print("Model not initialized properly")
                return []
                
            emb = await self._embed_async(text)
            
            if self.sb is None:
                print("Supabase client not initialized properly")
                return []
                
            rows = (
                self.sb.rpc(
                    "match_reference_reports",
                    {"query_embedding": emb, "k": k}
                ).execute()
                .data
            )
            return rows or []
        except Exception as e:
            print(f"Error in retrieve: {e}")
            return []