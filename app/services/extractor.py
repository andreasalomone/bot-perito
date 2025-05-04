import base64, io
from docx import Document
import pdfplumber
from typing import BinaryIO, Tuple
from PIL import Image
from app.core.ocr import ocr
from app.core.config import settings

def _pdf_to_text(f: BinaryIO) -> str:
    with pdfplumber.open(f) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)

def _docx_to_text(f: BinaryIO) -> str:
    doc = Document(f)
    return "\n".join(p.text for p in doc.paragraphs)

def _image_handler(fname: str, f: BinaryIO) -> Tuple[str, str]:
    """Return (text, img_token). img_token is base64 if vision enabled."""
    f.seek(0)
    text = ocr(f)
    if len(text.strip()) > 30 or not settings.allow_vision:
        return text, ""  # good OCR or vision disabled
    # no text ➜ pass downsized image to LLM
    f.seek(0)
    img = Image.open(f).convert("RGB")
    img.thumbnail((512, 512))  # keep prompt small
    buf = io.BytesIO(); img.save(buf, format="JPEG", quality=70); buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    token = f"data:image/jpeg;base64,{b64}"
    return "", token

_HANDLERS = {
    "pdf": _pdf_to_text,
    "docx": _docx_to_text,
    "doc": _docx_to_text,
}

def extract(fname: str, f: BinaryIO) -> Tuple[str, str]:
    ext = fname.lower().split(".")[-1]
    if ext in _HANDLERS:
        return _HANDLERS[ext](f), ""
    if ext in {"png", "jpg", "jpeg"}:
        return _image_handler(fname, f)
    return f.read().decode(errors="ignore"), ""

def guard_corpus(corpus: str) -> str:
    if len(corpus) > settings.max_prompt_chars:
        return corpus[:settings.max_prompt_chars] + "\n\n[TESTO TRONCATO PER LIMITE TOKEN]"
    return corpus