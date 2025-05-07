# app/api/routes.py

import json
import logging
from uuid import uuid4
from tempfile import TemporaryDirectory
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from docx import Document

from app.core.config import settings
from app.core.validation import validate_upload
from app.services.extractor import extract, guard_corpus, extract_damage_image
from app.services.llm import (
    build_prompt,
    call_llm,
    extract_json,
    LLMError,
    JSONParsingError,
)
from app.services.rag import RAGService
from app.services.pipeline import PipelineService
from app.services.doc_builder import inject
from app.core.security import verify_api_key, Depends

# Configure module logger
logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate(
    files: List[UploadFile] = File(...),
    damage_imgs: List[UploadFile] = File(None),
    notes: str = Form(""),
):
    """
    End-point principale:
      1. Estrae testo e immagini dai file caricati
      2. Recupera casi simili (RAG)
      3. Genera outline, espande sezioni e armonizza il testo
      4. Estrae i campi "semplici" (client, date, polizze…)
      5. Unisce tutto e inietta nel DOCX
      6. Restituisce il DOCX via StreamingResponse
    """
    request_id = str(uuid4())
    logger.info(
        "[%s] Starting report generation with %d files and %d damage images",
        request_id,
        len(files),
        len(damage_imgs or []),
    )

    try:
        with TemporaryDirectory():
            # --- 0: validazione file input -------------------------------
            for f in files:
                await validate_upload(f, request_id)

            if damage_imgs:
                for img in damage_imgs:
                    await validate_upload(img, request_id)

            # --- 1: estrazione testo + immagini ------------------------
            texts, imgs = [], []
            for f in files:
                try:
                    txt, tok = extract(f.filename, f.file)
                    if txt:
                        texts.append(txt)
                    if tok:
                        imgs.append(tok)
                    logger.debug(
                        "[%s] Extracted from %s: text=%d chars, has_image=%s",
                        request_id,
                        f.filename,
                        len(txt) if txt else 0,
                        bool(tok),
                    )
                except Exception as e:
                    logger.error(
                        "[%s] Failed to extract from %s: %s",
                        request_id,
                        f.filename,
                        str(e),
                        exc_info=True,
                    )
                    raise HTTPException(400, f"Failed to process file {f.filename}")

            for p in damage_imgs or []:
                try:
                    _, tok = extract_damage_image(p.file)
                    imgs.append(tok)
                    logger.debug(
                        "[%s] Extracted damage image from %s", request_id, p.filename
                    )
                except Exception as e:
                    logger.error(
                        "[%s] Failed to extract damage image from %s: %s",
                        request_id,
                        p.filename,
                        str(e),
                        exc_info=True,
                    )
                    raise HTTPException(
                        400, f"Failed to process damage image {p.filename}"
                    )

            if len(imgs) > 10:
                logger.warning(
                    "[%s] Too many images (%d), truncating to 10", request_id, len(imgs)
                )
                imgs = imgs[:10]

            corpus = guard_corpus("\n\n".join(texts))
            template_path = "app/templates/template.docx"
            try:
                template_excerpt = "\n".join(
                    p.text for p in Document(template_path).paragraphs[:8]
                )
                logger.debug(
                    "[%s] Loaded template excerpt: %d chars",
                    request_id,
                    len(template_excerpt),
                )
            except Exception as e:
                logger.error(
                    "[%s] Failed to load template: %s",
                    request_id,
                    str(e),
                    exc_info=True,
                )
                raise HTTPException(500, "Template loading failed")

            # --- 2: retrieval casi simili --------------------------------
            try:
                rag = RAGService()
                similar_cases = await rag.retrieve(corpus, k=3)
                logger.info(
                    "[%s] Retrieved %d similar cases", request_id, len(similar_cases)
                )
            except Exception as e:
                logger.error(
                    "[%s] RAG retrieval failed: %s", request_id, str(e), exc_info=True
                )
                raise HTTPException(500, "Failed to retrieve similar cases")

            # --- 3: estrai i campi "semplici" via prompt base -------------
            try:
                base_prompt = build_prompt(
                    template_excerpt, corpus, imgs, notes, similar_cases=similar_cases
                )
                if len(base_prompt) > settings.max_total_prompt_chars:
                    logger.warning(
                        "[%s] Prompt too large: %d chars", request_id, len(base_prompt)
                    )
                    raise HTTPException(413, "Prompt troppo grande o troppi allegati")

                raw_base = await call_llm(base_prompt)
                base_ctx = extract_json(raw_base)
                logger.info(
                    "[%s] Successfully extracted base context fields", request_id
                )

            except LLMError as e:
                logger.error(
                    "[%s] LLM call failed: %s", request_id, str(e), exc_info=True
                )
                raise HTTPException(500, f"LLM processing failed (id: {request_id})")
            except JSONParsingError as e:
                logger.error(
                    "[%s] JSON parsing failed: %s", request_id, str(e), exc_info=True
                )
                raise HTTPException(
                    500, f"Failed to parse LLM response (id: {request_id})"
                )

            # --- 4: pipeline multi-step outline→sezioni→armonizza --------
            try:
                pipeline = PipelineService()
                section_map = await pipeline.run(
                    template_excerpt, corpus, imgs, notes, similar_cases
                )
                logger.info(
                    "[%s] Pipeline processing completed successfully", request_id
                )
            except Exception:
                logger.exception("[%s] Pipeline processing failed", request_id)
                raise HTTPException(500, f"Report generation failed (id: {request_id})")

            # --- 5: unisci contesto finale per doc_builder ----------------
            final_ctx = {
                **base_ctx,  # client, date, vs_rif, polizza, allegati…
                **section_map,  # dinamica_eventi, accertamenti, quantific., commento
            }

            # --- 6: merge nel template e streaming -----------------------
            try:
                docx_bytes = inject(
                    template_path, json.dumps(final_ctx, ensure_ascii=False)
                )
                logger.info("[%s] Successfully generated DOCX report", request_id)
                return StreamingResponse(
                    iter([docx_bytes]),
                    media_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    headers={"Content-Disposition": "attachment; filename=report.docx"},
                )
            except Exception:
                logger.exception("[%s] Failed to generate final document", request_id)
                raise HTTPException(
                    500, f"Document generation failed (id: {request_id})"
                )

    except HTTPException:
        raise
    except Exception:
        logger.exception("[%s] Unexpected error during report generation", request_id)
        return PlainTextResponse(
            f"Errore interno (id: {request_id}). Contattare il supporto con questo ID.",
            status_code=500,
        )
