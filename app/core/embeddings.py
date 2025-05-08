import logging
import os

import dotenv
import requests

dotenv.load_dotenv()

HF_MODEL = (
    "sentence-transformers/all-MiniLM-L6-v2"  # or any model that returns embeddings
)
HF_URL = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{HF_MODEL}"

log = logging.getLogger(__name__)


def _get_headers() -> dict[str, str]:
    token = os.getenv("HF_API_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not token:
        raise RuntimeError(
            "HF API token not found. Set HF_API_TOKEN or HUGGINGFACEHUB_API_TOKEN env var."
        )
    return {"Authorization": f"Bearer {token}"}


def embed(text: str) -> list[float]:
    try:
        headers = _get_headers()
        res = requests.post(
            HF_URL,
            headers=headers,
            json={"inputs": text, "options": {"wait_for_model": True}},
        )
        res.raise_for_status()
        return res.json()[0]  # HF returns List[List[float]]
    except Exception:
        log.exception("Embedding call failed")
        raise
