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
from app.services.rag import RAGService
from app.services.pipeline import PipelineService
from app.services.doc_builder import inject

router = APIRouter()


@router.post("/generate")
async def generate(
    files: List[UploadFile] = File(...),
    damage_imgs: List[UploadFile] = File(None),
    notes: str = Form("")
):
    """
    End-point principale:
      1. Estrae testo e immagini dai file caricati
      2. Recupera casi simili (RAG)
      3. Genera outline, espande sezioni e armonizza il testo
      4. Estrae i campi “semplici” (client, date, polizze…)
      5. Unisce tutto e inietta nel DOCX
      6. Restituisce il DOCX via StreamingResponse
    """
    try:
        with TemporaryDirectory():
            # --- 1: estrazione testo + immagini ------------------------
            texts, imgs = [], []
            for f in files:
                txt, tok = extract(f.filename, f.file)
                if txt:
                    texts.append(txt)
                if tok:
                    imgs.append(tok)
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

            # --- 2: retrieval casi simili --------------------------------
            rag = RAGService()
            similar_cases = await rag.retrieve(corpus, k=3)

            # --- 3: estrai i campi "semplici" via prompt base -------------
            base_prompt = build_prompt(
                template_excerpt, corpus, imgs, notes,
                similar_cases=similar_cases
            )
            if len(base_prompt) > settings.max_total_prompt_chars:
                raise HTTPException(413, "Prompt troppo grande o troppi allegati")
            raw_base = await call_llm(base_prompt)
            try:
                base_ctx = extract_json(raw_base)
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Errore parsing JSON base: {e}"
                )

            # --- 4: pipeline multi-step outline→sezioni→armonizza --------
            pipeline = PipelineService()
            section_map = await pipeline.run(
                template_excerpt, corpus, imgs, notes, similar_cases
            )

            # --- 5: unisci contesto finale per doc_builder ----------------
            final_ctx = {
                **base_ctx,      # client, date, vs_rif, polizza, allegati…
                **section_map    # dinamica_eventi, accertamenti, quantificazione, commento
            }

            # --- 6: merge nel template e streaming -----------------------
            docx_bytes = inject(
                template_path,
                json.dumps(final_ctx, ensure_ascii=False)
            )
            return StreamingResponse(
                iter([docx_bytes]),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": "attachment; filename=report.docx"},
            )

    except HTTPException:
        raise
    except Exception as e:
        # qui puoi loggare con logger.exception(e)
        return PlainTextResponse(f"Errore interno: {e}", status_code=500)