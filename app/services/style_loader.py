from pathlib import Path
from docx import Document
from functools import lru_cache
from app.core.config import settings

@lru_cache
def load_style_samples() -> str:
    ref_path = Path(settings.reference_dir)
    if not ref_path.exists():
        return ""

    chunks = []
    for docx_file in ref_path.glob("*.docx"):
        try:
            doc = Document(docx_file)
            para_text = "\n".join(
                p.text for p in doc.paragraphs[: settings.max_style_paragraphs]
            )
            chunks.append(para_text.strip())
        except Exception:
            continue  # skip corrupt/unsupported files
    return "\n---\n".join(chunks)