from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List
from uuid import uuid4

import async_lru
import dotenv
from supabase import create_client

from app.core.embeddings import embed

# Configure module logger
logger = logging.getLogger(__name__)

dotenv.load_dotenv()


class RAGError(Exception):
    """Base exception for RAG-related errors"""


class RAGService:
    """Singleton KISS per retrieval semantico."""

    _instance: "RAGService" | None = None

    def __new__(cls):
        if cls._instance is None:
            logger.info("Creating new RAGService instance")
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        try:
            url = os.environ["SUPABASE_URL"]
            key = os.environ["SUPABASE_ANON_KEY"]  # solo lettura

            if not url or not key:
                logger.error("Missing Supabase environment variables")
                raise RAGError("Missing required environment variables")

            logger.info("Initializing Supabase client")
            self.sb = create_client(url, key)

            # No local embedding model; will call external API via embed()

        except Exception as e:
            logger.exception("Failed to initialize RAGService")
            # Set default values to prevent attribute errors
            self.sb = None
            raise RAGError("Failed to initialize RAG service") from e

    # cache locale degli embedding per richieste ripetute
    @async_lru.alru_cache(maxsize=128)
    async def _embed_async(self, text: str) -> list[float]:
        try:
            return await asyncio.to_thread(embed, text)
        except Exception as e:
            logger.exception("Failed to generate embedding")
            raise RAGError("Failed to generate embedding") from e

    async def retrieve(self, text: str, k: int = 3) -> List[Dict]:
        """Ritorna lista di dizionari: id, title, snippet."""
        request_id = str(uuid4())
        logger.info(
            "[%s] Starting semantic retrieval for text length %d, k=%d",
            request_id,
            len(text),
            k,
        )

        try:
            if self.sb is None:
                logger.error(
                    "[%s] Supabase client not initialized properly", request_id
                )
                raise RAGError("Supabase client not initialized")

            logger.debug("[%s] Generating embedding", request_id)
            emb = await self._embed_async(text)

            logger.debug("[%s] Querying Supabase for similar documents", request_id)
            # Offload supabase RPC to thread to avoid blocking event loop
            resp = await asyncio.to_thread(
                lambda: self.sb.rpc(
                    "match_reference_reports", {"query_embedding": emb, "k": k}
                ).execute()
            )
            rows = resp.data

            result = rows or []
            logger.info("[%s] Retrieved %d similar documents", request_id, len(result))
            return result

        except RAGError:
            raise
        except Exception as e:
            logger.exception("[%s] Unexpected error during retrieval", request_id)
            raise RAGError("Failed to retrieve similar documents") from e
