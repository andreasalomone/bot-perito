import logging
import os

import requests

HF_MODEL = (
    "sentence-transformers/all-MiniLM-L6-v2"  # or any model that returns embeddings
)
HF_URL = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{HF_MODEL}"
HEADERS = {"Authorization": f"Bearer {os.environ['HUGGINGFACEHUB_API_TOKEN']}"}

log = logging.getLogger(__name__)


def embed(text: str) -> list[float]:
    try:
        res = requests.post(
            HF_URL,
            headers=HEADERS,
            json={"inputs": text, "options": {"wait_for_model": True}},
        )
        res.raise_for_status()
        return res.json()[0]  # HF returns List[List[float]]
    except Exception:
        log.exception("Embedding call failed")
        raise
