import asyncio
from pathlib import Path

from async_lru import alru_cache
from docx import Document

from app.core.config import settings


@alru_cache(maxsize=1)
async def load_style_samples() -> str:
    ref_path = Path(settings.reference_dir)
    if not ref_path.exists():
        return ""

    def _sync_extract_style_from_doc(path_str: str) -> str:
        doc = Document(str(path_str))
        return "\n".join(p.text for p in doc.paragraphs[: settings.max_style_paragraphs])

    chunks = []
    for docx_file in ref_path.glob("*.docx"):
        try:
            para_text: str = await asyncio.to_thread(_sync_extract_style_from_doc, str(docx_file))
            if para_text.strip():
                chunks.append(para_text.strip())
        except Exception:
            continue  # skip corrupt/unsupported files
    return "\n---\n".join(chunks)
