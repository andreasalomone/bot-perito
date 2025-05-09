import asyncio
import inspect
import json
import logging
from tempfile import TemporaryDirectory
from typing import List, Tuple
from uuid import uuid4

from docx import Document
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.security import Depends, verify_api_key
from app.core.validation import validate_upload
from app.services.doc_builder import DocBuilderError, inject
from app.services.extractor import (
    ExtractorError,
    extract,
    extract_damage_image,
    guard_corpus,
)
from app.services.llm import (
    JSONParsingError,
    LLMError,
    build_prompt,
    call_llm,
    extract_json,
)
from app.services.pipeline import PipelineError, PipelineService
from app.services.rag import RAGError, RAGService

# Configure module logger
logger = logging.getLogger(__name__)

router = APIRouter()


# Add helper functions for text and image extraction
async def _extract_single_file(
    file: UploadFile, request_id: str
) -> Tuple[str | None, str | None]:
    try:
        txt, tok = extract(file.filename or "", file.file)
        logger.debug(
            "[%s] Extracted from %s: text=%d chars, has_image=%s",
            request_id,
            file.filename,
            len(txt) if txt else 0,
            bool(tok),
        )
        return txt, tok
    except ExtractorError as e:
        logger.error(
            "[%s] Extraction error from %s: %s",
            request_id,
            file.filename,
            str(e),
            exc_info=True,
        )
        # Propagate the error to be handled by the gather call
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "[%s] Failed to extract from %s: %s",
            request_id,
            file.filename,
            str(e),
            exc_info=True,
        )
        # Propagate the error to be handled by the gather call
        raise HTTPException(
            status_code=400, detail=f"Failed to process file {file.filename}"
        )


async def extract_texts(
    files: List[UploadFile], request_id: str
) -> Tuple[List[str], List[str]]:
    tasks = [_extract_single_file(f, request_id) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    texts: List[str] = []
    imgs: List[str] = []

    for result in results:
        if isinstance(result, Exception):
            # If it's an HTTPException, re-raise it directly
            if isinstance(result, HTTPException):
                raise result
            # For other exceptions, wrap them in a generic HTTPException or handle as appropriate
            raise HTTPException(
                status_code=500,
                detail=f"An unexpected error occurred during file extraction: {str(result)}",
            )

        txt, tok = result
        if txt:
            texts.append(txt)
        if tok:
            imgs.append(tok)

    return texts, imgs


async def _process_single_image(damage_img: UploadFile, request_id: str) -> str:
    try:
        _, tok = extract_damage_image(damage_img.file)
        logger.debug(
            "[%s] Extracted damage image from %s", request_id, damage_img.filename
        )
        return tok
    except ExtractorError as e:
        logger.error(
            "[%s] Extraction error for damage image %s: %s",
            request_id,
            damage_img.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            "[%s] Failed to extract damage image from %s: %s",
            request_id,
            damage_img.filename,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Failed to process damage image {damage_img.filename}",
        )


async def process_images(damage_imgs: List[UploadFile], request_id: str) -> List[str]:
    if not damage_imgs:
        return []
    tasks = [_process_single_image(p, request_id) for p in damage_imgs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    imgs: List[str] = []
    for result in results:
        if isinstance(result, Exception):
            if isinstance(result, HTTPException):
                raise result
            raise HTTPException(
                status_code=500,
                detail=f"An unexpected error occurred during image processing: {str(result)}",
            )
        imgs.append(result)

    return imgs


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate(
    files: List[UploadFile] = File(...),
    damage_imgs: List[UploadFile] = File(None),
    notes: str = Form(""),
    use_rag: bool = Form(False),
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
            texts, imgs = await extract_texts(files, request_id)
            imgs += await process_images(damage_imgs or [], request_id)
            if len(imgs) > 10:
                logger.warning(
                    "[%s] Too many images (%d), truncating to 10", request_id, len(imgs)
                )
                imgs = imgs[:10]

            corpus = guard_corpus("\n\n".join(texts))
            template_path = str(settings.template_path)
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

            # --- 2: optional retrieval di casi simili (RAG) -------------
            similar_cases: List[dict] = []
            if use_rag:
                try:
                    rag = RAGService()
                    similar_cases = await rag.retrieve(corpus, k=3)
                    logger.info(
                        "[%s] Retrieved %d similar cases",
                        request_id,
                        len(similar_cases),
                    )
                except RAGError as e:
                    logger.error(
                        "[%s] RAG error: %s",
                        request_id,
                        str(e),
                        exc_info=True,
                    )
                    raise HTTPException(500, str(e))
                except Exception as e:
                    logger.error(
                        "[%s] RAG retrieval failed: %s",
                        request_id,
                        str(e),
                        exc_info=True,
                    )
                    raise HTTPException(500, "Failed to retrieve similar cases")

            # --- 3: estrai i campi "semplici" via prompt base -------------
            try:
                base_prompt = build_prompt(
                    template_excerpt, corpus, imgs, notes, similar_cases=similar_cases
                )
                if len(base_prompt) > settings.max_total_prompt_chars:
                    raise HTTPException(413, "Prompt troppo grande o troppi allegati")

                # Support both async and sync call_llm stubs
                res = call_llm(base_prompt)
                if inspect.isawaitable(res):
                    raw_base = await res
                else:
                    raw_base = res
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
                    template_excerpt,
                    corpus,
                    imgs,
                    notes,
                    similar_cases,
                    extra_styles="",
                )
                logger.info(
                    "[%s] Pipeline processing completed successfully", request_id
                )
            except PipelineError as e:
                logger.error(
                    "[%s] Pipeline error: %s",
                    request_id,
                    str(e),
                    exc_info=True,
                )
                raise HTTPException(500, str(e))
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
            except DocBuilderError as e:
                logger.error(
                    "[%s] Document builder error: %s",
                    request_id,
                    str(e),
                    exc_info=True,
                )
                raise HTTPException(500, str(e))
            except Exception:
                logger.exception("[%s] Failed to generate final document", request_id)
                raise HTTPException(
                    500, f"Document generation failed (id: {request_id})"
                )

    except HTTPException:
        raise
    except Exception:
        logger.exception("[%s] Unexpected error during report generation", request_id)
        raise HTTPException(
            500,
            f"Errore interno (id: {request_id}). Contattare il supporto con questo ID.",
        )
