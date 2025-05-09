import asyncio
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

# Constants
DEFAULT_REPORT_FILENAME = "report.docx"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MAX_IMAGES_IN_REPORT = 10  # As per previous logic
RAG_DEFAULT_K = 3  # As per previous logic


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
            # This specific error is internal to extraction, better to raise a specific internal error
            # or let the main handler catch it as a generic 500.
            # For now, letting it propagate to be caught by the caller of extract_texts
            logger.error(
                "[%s] Unexpected error during file extraction part: %s",
                request_id,
                str(result),
                exc_info=True,
            )
            raise result

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

    imgs_tokens: List[str] = []  # Renamed to avoid conflict
    for result in results:
        if isinstance(result, Exception):
            if isinstance(result, HTTPException):
                raise result
            # Similar to extract_texts, let original exception propagate
            logger.error(
                "[%s] Unexpected error during image processing part: %s",
                request_id,
                str(result),
                exc_info=True,
            )
            raise result

        imgs_tokens.append(result)

    return imgs_tokens


async def _validate_and_extract_files(
    files: List[UploadFile], damage_imgs: List[UploadFile] | None, request_id: str
) -> Tuple[str, List[str]]:
    """Validates and extracts text and image tokens from uploaded files."""
    for f in files:
        await validate_upload(f, request_id)
    if damage_imgs:
        for img_file in damage_imgs:
            await validate_upload(img_file, request_id)

    texts_content, extracted_imgs = await extract_texts(files, request_id)
    if damage_imgs:
        extracted_imgs += await process_images(damage_imgs, request_id)

    if len(extracted_imgs) > MAX_IMAGES_IN_REPORT:
        logger.warning(
            "[%s] Too many images (%d), truncating to %d",
            request_id,
            len(extracted_imgs),
            MAX_IMAGES_IN_REPORT,
        )
        extracted_imgs = extracted_imgs[:MAX_IMAGES_IN_REPORT]

    corpus = guard_corpus("\n\n".join(texts_content))
    return corpus, extracted_imgs


async def _load_template_excerpt(template_path: str, request_id: str) -> str:
    """Loads the first few paragraphs of the template as an excerpt."""
    try:
        # Consider caching this if template_path rarely changes and loading is slow
        template_doc = Document(template_path)
        template_excerpt = "\n".join(
            p.text for p in template_doc.paragraphs[:8]
        )  # Keep 8 as per original
        logger.debug(
            "[%s] Loaded template excerpt: %d chars",
            request_id,
            len(template_excerpt),
        )
        return template_excerpt
    except Exception as e:
        logger.error(
            "[%s] Failed to load template for excerpt: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        # This error should be critical for the generation process
        raise HTTPException(
            status_code=500, detail="Template loading failed for excerpt"
        )


async def _retrieve_similar_cases(
    corpus: str, use_rag: bool, request_id: str
) -> List[dict]:
    """Retrieves similar cases using RAGService if use_rag is True."""
    if not use_rag:
        return []
    try:
        rag = RAGService()  # Instantiated here as it's only used in this step
        similar_cases = await rag.retrieve(corpus, k=RAG_DEFAULT_K)
        logger.info("[%s] Retrieved %d similar cases", request_id, len(similar_cases))
        return similar_cases
    except RAGError as e:
        logger.error("[%s] RAG error: %s", request_id, str(e), exc_info=True)
        # Propagate as HTTPException to be caught by main handler
        raise HTTPException(status_code=500, detail=f"RAG processing failed: {str(e)}")
    except Exception as e:
        logger.error(
            "[%s] RAG retrieval failed unexpectedly: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve similar cases")


async def _extract_base_context(
    template_excerpt: str,
    corpus: str,
    imgs: List[str],
    notes: str,
    similar_cases: List[dict],
    request_id: str,
) -> dict:
    """Extracts base context fields using LLM."""
    try:
        base_prompt = build_prompt(
            template_excerpt, corpus, imgs, notes, similar_cases=similar_cases
        )
        if len(base_prompt) > settings.max_total_prompt_chars:
            logger.warning(
                "[%s] Prompt too large: %d chars", request_id, len(base_prompt)
            )
            raise HTTPException(
                status_code=413, detail="Prompt too large or too many attachments"
            )

        raw_base = await call_llm(base_prompt)  # Simplified async call
        base_ctx = extract_json(raw_base)
        logger.info("[%s] Successfully extracted base context fields", request_id)
        return base_ctx
    except LLMError as e:
        logger.error(
            "[%s] LLM call for base context failed: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"LLM processing for base fields failed: {str(e)}"
        )
    except JSONParsingError as e:
        logger.error(
            "[%s] JSON parsing for base context failed: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"JSON parsing for base fields failed: {str(e)}"
        )
    # HTTPException for prompt size is already raised and will be caught by the main handler


async def _run_processing_pipeline(
    template_excerpt: str,
    corpus: str,
    imgs: List[str],
    notes: str,
    similar_cases: List[dict],
    request_id: str,
) -> dict:
    """Runs the multi-step processing pipeline."""
    try:
        pipeline = PipelineService()  # Instantiated here
        section_map = await pipeline.run(
            template_excerpt,
            corpus,
            imgs,
            notes,
            similar_cases,
            extra_styles="",  # As per original, could be a setting
        )
        logger.info("[%s] Pipeline processing completed successfully", request_id)
        return section_map
    except PipelineError as e:
        logger.error("[%s] Pipeline error: %s", request_id, str(e), exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Pipeline processing failed: {str(e)}"
        )
    except Exception as e:  # Catch any other unexpected errors from pipeline
        logger.error(
            "[%s] Unexpected pipeline processing error: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Report generation pipeline failed (id: {request_id})",
        )


async def _generate_and_stream_docx(
    template_path: str, final_context: dict, request_id: str
) -> StreamingResponse:
    """Generates the DOCX file from the final context and prepares it for streaming."""
    try:
        docx_bytes = inject(
            template_path, json.dumps(final_context, ensure_ascii=False)
        )
        logger.info("[%s] Successfully generated DOCX report", request_id)
        return StreamingResponse(
            iter([docx_bytes]),
            media_type=DOCX_MEDIA_TYPE,
            headers={
                "Content-Disposition": f"attachment; filename={DEFAULT_REPORT_FILENAME}"
            },
        )
    except DocBuilderError as e:
        logger.error(
            "[%s] Document builder error: %s", request_id, str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Document builder error: {str(e)}")
    except Exception as e:  # Catch any other unexpected errors from doc injection
        logger.error(
            "[%s] Failed to generate final document: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Document generation failed (id: {request_id})"
        )


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate(
    files: List[UploadFile] = File(...),
    damage_imgs: List[UploadFile] | None = File(
        None
    ),  # Changed default to None for clarity
    notes: str = Form(""),
    use_rag: bool = Form(False),
):
    request_id = str(uuid4())
    logger.info(
        "[%s] Starting report generation with %d files and %d damage images",
        request_id,
        len(files),
        len(damage_imgs or []),
    )

    try:
        # TemporaryDirectory is still useful if any underlying service needs file paths
        # Even if extract/inject could work with BytesIO, other parts or future changes might rely on it.
        # The audit mentions "This is often a trade-off with library compatibility." - safer to keep.
        with TemporaryDirectory():
            # --- Step 1: Validate inputs and extract content ---
            corpus, imgs = await _validate_and_extract_files(
                files, damage_imgs, request_id
            )

            # --- Step 2: Load template excerpt ---
            template_path = str(settings.template_path)
            template_excerpt = await _load_template_excerpt(template_path, request_id)

            # --- Step 3: Retrieve similar cases (RAG) ---
            similar_cases = await _retrieve_similar_cases(corpus, use_rag, request_id)

            # --- Step 4: Extract base context (simple fields) ---
            base_ctx = await _extract_base_context(
                template_excerpt, corpus, imgs, notes, similar_cases, request_id
            )

            # --- Step 5: Run main processing pipeline (outline, sections, harmonize) ---
            section_map = await _run_processing_pipeline(
                template_excerpt, corpus, imgs, notes, similar_cases, request_id
            )

            # --- Step 6: Combine contexts ---
            final_ctx = {**base_ctx, **section_map}

            # --- Step 7: Generate and stream DOCX ---
            return await _generate_and_stream_docx(template_path, final_ctx, request_id)

    except HTTPException:  # Re-raise HTTPExceptions directly
        raise
    except Exception as e:  # Catch-all for truly unexpected errors
        # Log the full exception for unexpected errors not caught by helpers
        logger.exception(
            "[%s] Unexpected error during report generation orchestration: %s",
            request_id,
            str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected internal error occurred (id: {request_id}). Please contact support.",
        )
