"""
Estrae testo dai DOCX in data/reference_reports/,
genera embedding con Sentence‑Transformers
e inserisce in Supabase.
"""

import os
from pathlib import Path
from datetime import date

import dotenv
from sentence_transformers import SentenceTransformer
from docx import Document
from supabase import create_client
from tqdm import tqdm

# --- Config -----------------------------------------------------
dotenv.load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]  # service‑role
REF_DIR = Path("data/reference_reports")
EMB_MODEL_NAME = "all-MiniLM-L6-v2"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
model = SentenceTransformer(EMB_MODEL_NAME, device="cpu")  # CPU ok


# --- Helpers ----------------------------------------------------
def extract_text(docx_path: Path) -> str:
    doc = Document(docx_path)
    # rimuovi righe vuote
    return "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())


# --- Main -------------------------------------------------------
def main() -> None:
    for file in tqdm(sorted(REF_DIR.glob("*.docx"))):
        text = extract_text(file)
        if len(text) < 100:
            print(f"✘ Salto {file.name}: troppo corto")
            continue

        emb = model.encode(text).tolist()  # → list[float]

        supabase.table("reference_reports").insert(
            {
                "title": file.stem.replace("_", " ").capitalize(),
                "date": str(date.today()),
                "content": text,
                "embedding": emb,
            }
        ).execute()

        print(f"✓ Indicizzato {file.name}")


if __name__ == "__main__":
    main()
