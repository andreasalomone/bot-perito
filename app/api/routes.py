# app/api/routes.py
import json
from tempfile import TemporaryDirectory
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from docx import Document

from app.core.config import settings
from app.services.extractor import extract, guard_corpus, extract_damage_image
from app.services.llm import build_prompt, call_llm, extract_json
from app.services.doc_builder import inject

router = APIRouter()


@router.post("/generate")
async def generate(
    files: List[UploadFile] = File(...),
    damage_imgs: List[UploadFile] = File(None),
    notes: str = Form("")
):
    """
    End‑point principale:
      1. Estrae testo e immagini dai file caricati
      2. Costruisce il prompt e chiama il modello
      3. Valida/normalizza il JSON di risposta
      4. Lo fonde nel template con DocxTpl
      5. Restituisce il DOCX via StreamingResponse
    """
    try:
        with TemporaryDirectory():
            # --- 1: estrazione ------------------------------------------------
            texts, imgs = [], []
            for f in files:
                txt, tok = extract(f.filename, f.file)
                if txt:
                    texts.append(txt)
                if tok:
                    imgs.append(tok)

            # --- foto danni --------------------------------------------------
            for p in damage_imgs or []:
                _, tok = extract_damage_image(p.file)
                imgs.append(tok)

            if len(imgs) > 10:                   
                imgs = imgs[:10]

            corpus = guard_corpus("\n\n".join(texts))
            template_path = "app/templates/template.docx"
            template_excerpt = "\n".join(
                p.text for p in Document(template_path).paragraphs[:8]
            )

            # --- 2: prompt + LLM ---------------------------------------------
            prompt = build_prompt(template_excerpt, corpus, imgs, notes)
            # Includiamo un limite più permissivo che consideri anche
            # l'eventuale base-64 delle immagini. Usiamo un parametro
            # dedicato così da non dover toccare il truncation del solo
            # corpus testuale (max_prompt_chars).
            if len(prompt) > settings.max_total_prompt_chars:
                raise HTTPException(413, "File troppo grande o troppi allegati")

            raw_reply = await call_llm(prompt)
            # print("LLM RAW >>>", raw_reply[:400])  # debug

            # --- 3: validazione JSON -----------------------------------------
            try:
                ctx = extract_json(raw_reply)  # dict pulito
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Modello non ha restituito JSON valido: {e}"
                )

            # --- 4: merge nel template ---------------------------------------
            docx_bytes = inject(
                template_path,
                json.dumps(ctx, ensure_ascii=False)  # inject vuole string
            )

            # --- 5: risposta streaming ---------------------------------------
            return StreamingResponse(
                iter([docx_bytes]),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": "attachment; filename=report.docx"},
            )

    except HTTPException:
        raise  # rilancia per FastAPI
    except Exception as e:
        # puoi loggare e.g. logger.exception(e)
        return PlainTextResponse(f"Errore interno: {e}", status_code=500)