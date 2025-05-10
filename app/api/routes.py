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
from app.models.report_models import ClarificationPayload, ReportContext
from app.services.clarification_service import ClarificationService
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
            status_code=500,
            detail="An unexpected error occurred during text extraction.",
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
            status_code=500,
            detail="An unexpected error occurred during image processing.",
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
        raise HTTPException(status_code=500, detail="Error loading template excerpt.")


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
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving similar cases.",
        )


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
    except Exception as e:
        if isinstance(e, HTTPException):  # Re-raise if it's already an HTTPException
            raise e
        logger.error(
            "[%s] Unexpected error in base context extraction: %s",  # Clarified log message
            request_id,
            str(e),
            exc_info=True,
        )
        # Raise PipelineError for other generic errors to be handled consistently upstream
        raise PipelineError(f"Unexpected error during base context extraction: {e}")


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
        section_map = None
        async for update_json_str in pipeline.run(
            template_excerpt,
            corpus,
            imgs,
            notes,
            similar_cases,
            extra_styles="",  # As per original, could be a setting
        ):
            try:
                update_data = json.loads(update_json_str)
                if update_data.get("type") == "data" and "payload" in update_data:
                    section_map = update_data["payload"]
                    # Assuming the 'data' payload is the final section_map and we can break
                    break
                elif update_data.get("type") == "error":
                    # Propagate error from pipeline
                    error_message = update_data.get(
                        "message",
                        "Unknown pipeline error during non-streaming generation",
                    )
                    logger.error(
                        "[%s] Pipeline error during non-streaming generation: %s",
                        request_id,
                        error_message,
                    )
                    raise PipelineError(error_message)
            except json.JSONDecodeError:
                logger.warning(
                    "[%s] Non-JSON message from pipeline during non-streaming generation: %s",
                    request_id,
                    update_json_str,
                )
                # Decide if this is a critical error for non-streaming mode
                # For now, let's assume it might be, or log and continue if appropriate
                raise PipelineError(
                    "Received malformed data from pipeline during non-streaming generation."
                )

        if section_map is None:
            logger.error(
                "[%s] Pipeline finished without returning section map in non-streaming mode.",
                request_id,
            )
            raise PipelineError("Pipeline did not return the expected section map.")
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
        raise PipelineError(
            f"An unexpected error occurred in the report generation pipeline: {e}"
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
            status_code=500,
            detail="An unexpected error occurred while generating the DOCX document.",
        )


# Helper function to manage the report generation stream
async def _stream_report_generation_logic(
    files: List[UploadFile],
    damage_imgs: List[UploadFile] | None,
    notes: str,
    use_rag: bool,
    # API key verification is handled by dependency, not passed here
):
    request_id = str(uuid4())
    logger.info(
        "[%s] Initiating streaming report generation: %d files, %d damage images, use_rag=%s",
        request_id,
        len(files),
        len(damage_imgs or []),
        use_rag,
    )

    # Store original inputs for request_artifacts
    original_notes = notes
    original_use_rag = use_rag
    # `files` and `damage_imgs` are harder to pass directly;
    # frontend will need to resubmit them if clarification is needed.
    # The plan specifies:
    # original_corpus, image_tokens, notes, use_rag, similar_cases_retrieved, initial_llm_base_fields
    # We will construct these as we go.

    section_map_from_pipeline = None

    try:
        with TemporaryDirectory():
            template_path_str = str(settings.template_path)

            yield json.dumps(
                {
                    "type": "status",
                    "message": "Validating inputs and extracting content...",
                }
            ) + "\n"
            corpus, imgs_tokens = await _validate_and_extract_files(
                files, damage_imgs, request_id
            )
            # `corpus` here is `original_corpus` for artifacts
            yield json.dumps(
                {
                    "type": "status",
                    "message": f"Content extracted: {len(corpus)} chars, {len(imgs_tokens)} images.",
                }
            ) + "\n"

            yield json.dumps(
                {"type": "status", "message": "Loading template excerpt..."}
            ) + "\n"
            template_excerpt = await _load_template_excerpt(
                template_path_str, request_id
            )
            yield json.dumps(
                {"type": "status", "message": "Template excerpt loaded."}
            ) + "\n"

            yield json.dumps(
                {
                    "type": "status",
                    "message": "Retrieving similar cases (if enabled)...",
                }
            ) + "\n"
            similar_cases = await _retrieve_similar_cases(
                corpus, use_rag, request_id
            )  # `similar_cases` for artifacts
            yield json.dumps(
                {
                    "type": "status",
                    "message": f"{len(similar_cases)} similar cases retrieved.",
                }
            ) + "\n"

            yield json.dumps(
                {
                    "type": "status",
                    "message": "Extracting base document context (LLM)...",
                }
            ) + "\n"
            base_ctx = await _extract_base_context(  # `base_ctx` is `initial_llm_base_fields` for artifacts
                template_excerpt, corpus, imgs_tokens, notes, similar_cases, request_id
            )
            yield json.dumps(
                {"type": "status", "message": "Base document context extracted."}
            ) + "\n"

            # Clarification Check
            clarification_service = ClarificationService()
            missing_info_list = clarification_service.identify_missing_fields(
                base_ctx, settings.CRITICAL_FIELDS_FOR_CLARIFICATION
            )

            if missing_info_list:
                logger.info(
                    "[%s] Clarification needed for %d fields.",
                    request_id,
                    len(missing_info_list),
                )
                request_artifacts = {
                    "original_corpus": corpus,
                    "image_tokens": imgs_tokens,  # These are the base64 encoded image tokens
                    "notes": original_notes,
                    "use_rag": original_use_rag,
                    "similar_cases_retrieved": similar_cases,
                    "initial_llm_base_fields": base_ctx,
                }
                yield json.dumps(
                    {
                        "type": "clarification_needed",  # Changed from "status"
                        "missing_fields": missing_info_list,
                        "request_artifacts": request_artifacts,
                    }
                ) + "\n"
                return  # Stop the stream here

            # If no clarification needed, proceed with pipeline
            yield json.dumps(
                {
                    "type": "status",
                    "message": "No immediate clarifications needed. Starting main report generation pipeline...",
                }
            ) + "\n"
            pipeline = PipelineService()
            async for pipeline_update_json_str in pipeline.run(
                template_excerpt,
                corpus,
                imgs_tokens,  # These are the base64 image tokens
                notes,
                similar_cases,
                extra_styles="",  # Assuming empty as per original setup
            ):
                try:
                    update_data = json.loads(pipeline_update_json_str)
                    if update_data.get("type") == "data" and "payload" in update_data:
                        # This is the harmonized_sections_dict from the pipeline
                        section_map_from_pipeline = update_data.get("payload")
                        # Yield a status update, don't pass the raw pipeline "data" type directly to client yet
                        yield json.dumps(
                            {
                                "type": "status",
                                "message": "Core content generation complete. Finalizing report data...",
                            }
                        ) + "\n"
                    elif update_data.get("type") == "error":
                        # Pass pipeline errors through
                        logger.error(
                            f"[{request_id}] Error from pipeline stream: {update_data.get('message')}"
                        )
                        yield pipeline_update_json_str + "\n"  # Forward the error
                        return  # Stop further processing if pipeline reported an error
                    else:
                        # Pass through other status updates from the pipeline
                        yield pipeline_update_json_str + "\n"
                except json.JSONDecodeError:
                    logger.warning(
                        f"[{request_id}] Non-JSON message from pipeline: {pipeline_update_json_str}"
                    )
                    # Yield a generic status if pipeline sends malformed JSON
                    yield json.dumps(
                        {"type": "status", "message": "Processing report sections..."}
                    ) + "\n"

            if section_map_from_pipeline is None:
                # This means pipeline.run() finished without yielding its 'data' payload, which is an error.
                logger.error(
                    f"[{request_id}] Pipeline completed without providing final section map."
                )
                raise PipelineError("Pipeline did not return section map data.")

            # Combine base context with the harmonized sections from the pipeline
            final_ctx = {**base_ctx, **section_map_from_pipeline}

            # Signal completion and send the final context.
            # The client-side script.js handles 'data' type by displaying payload and alerting about download.
            yield json.dumps(
                {
                    "type": "data",
                    "message": "Report data processing complete. Document download needs separate implementation.",
                    "payload": final_ctx,  # This is the complete context for the .docx
                }
            ) + "\n"

    except HTTPException as he:
        logger.warning(
            f"[{request_id}] HTTP Exception during stream: {he.status_code} - {he.detail}"
        )
        yield json.dumps({"type": "error", "message": str(he.detail)}) + "\n"
    except PipelineError as pe:
        logger.error(
            f"[{request_id}] PipelineError during stream orchestration: {str(pe)}",
            exc_info=True,
        )
        yield json.dumps(
            {"type": "error", "message": f"Pipeline processing error: {str(pe)}"}
        ) + "\n"
    except Exception as e:
        logger.exception(
            f"[{request_id}] Unexpected error during report generation stream: {str(e)}"
        )
        yield json.dumps(
            {
                "type": "error",
                "message": f"An unexpected server error occurred: {str(e)}",
            }
        ) + "\n"
    finally:
        logger.info(f"[{request_id}] Stream generation logic finished.")


@router.post("/generate", dependencies=[Depends(verify_api_key)])
async def generate(
    files: List[UploadFile] = File(...),
    damage_imgs: List[UploadFile] | None = File(None),
    notes: str = Form(""),
    use_rag: bool = Form(False),
):
    # This endpoint now returns a StreamingResponse that calls the generator
    return StreamingResponse(
        _stream_report_generation_logic(files, damage_imgs, notes, use_rag),
        media_type="application/x-ndjson",  # Newline Delimited JSON
    )


@router.post("/generate-with-clarifications", dependencies=[Depends(verify_api_key)])
async def generate_with_clarifications(
    payload: ClarificationPayload,
    # request: Request # For API key if not using dependency, but dependency is better
):
    request_id = str(uuid4())
    logger.info("[%s] Initiating report generation with clarifications.", request_id)

    try:
        user_clarifications = payload.clarifications
        artifacts = payload.request_artifacts

        # The initial_llm_base_fields is a ReportContext object, convert to dict for manipulation
        base_ctx = artifacts.initial_llm_base_fields.model_dump(exclude_none=True)

        # Merge clarifications: Update base_ctx with user_provided_clarifications
        # Only update if user provided a non-empty string value
        for key, value in user_clarifications.items():
            if value is not None and value.strip() != "":  # Check for non-empty string
                base_ctx[key] = value
            elif key in base_ctx and (
                value is None or value.strip() == ""
            ):  # If user explicitly empties a field
                base_ctx[key] = (
                    None  # Set to None if LLM should treat as missing, or "" if desired
                )

        # Retrieve necessary items from artifacts
        original_corpus = artifacts.original_corpus
        image_tokens = artifacts.image_tokens
        original_notes = artifacts.notes
        # original_use_rag = artifacts.use_rag # Not directly used by pipeline.run, similar_cases are passed
        similar_cases_retrieved = artifacts.similar_cases_retrieved

        template_path_str = str(settings.template_path)

        # 1. Load template excerpt (needed for the pipeline)
        # This logic is similar to _stream_report_generation_logic
        # yield_json_status = lambda type, msg: json.dumps({"type": type, "message": msg}) + "\\n" # dummy for non-streaming, not used

        # Re-use _load_template_excerpt. This is okay.
        template_excerpt = await _load_template_excerpt(template_path_str, request_id)

        # 2. Run processing pipeline (reusing the helper function)
        # _run_processing_pipeline expects: template_excerpt, corpus, imgs, notes, similar_cases, request_id
        # It returns section_map
        logger.info(
            "[%s] Running processing pipeline with clarifications...", request_id
        )
        section_map = await _run_processing_pipeline(
            template_excerpt=template_excerpt,
            corpus=original_corpus,
            imgs=image_tokens,
            notes=original_notes,
            similar_cases=similar_cases_retrieved,
            request_id=request_id,
            # extra_styles might need to be part of artifacts if dynamic, "" is default
        )
        logger.info("[%s] Pipeline processing completed.", request_id)

        # 3. Combine base_ctx (now updated with clarifications) and section_map
        final_ctx = {**base_ctx, **section_map}
        logger.debug(
            "[%s] Final context for DOCX: %s",
            request_id,
            json.dumps(final_ctx, indent=2, ensure_ascii=False)[:500] + "...",
        )

        # 4. Generate and stream DOCX
        # _generate_and_stream_docx expects: template_path, final_context, request_id
        # It returns a StreamingResponse
        logger.info("[%s] Generating DOCX with clarifications...", request_id)
        docx_response = await _generate_and_stream_docx(
            template_path=template_path_str,
            final_context=final_ctx,
            request_id=request_id,
        )
        logger.info("[%s] DOCX generation successful. Returning stream.", request_id)
        return docx_response

    except HTTPException as he:
        # Re-raise FastAPI's HTTPExceptions
        logger.error(
            "[%s] HTTPException during clarification processing: %s - %s",
            request_id,
            he.status_code,
            he.detail,
            exc_info=True,
        )
        raise he
    except (
        PipelineError,
        DocBuilderError,
        LLMError,
        JSONParsingError,
        RAGError,
        ExtractorError,
    ) as e:
        # Catch specific application errors and return a 500
        logger.error(
            "[%s] Application error during clarification processing: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed after clarifications: {str(e)}",
        )
    except Exception as e:
        # Catch-all for any other unexpected errors
        logger.error(
            "[%s] Unexpected error during clarification processing: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected server error occurred while generating the report with clarifications (id: {request_id}).",
        )


@router.post("/finalize-report", dependencies=[Depends(verify_api_key)])
async def finalize_report(
    final_ctx_payload: ReportContext,  # Expecting the full context
):
    request_id = str(uuid4())
    logger.info("[%s] Initiating report finalization and DOCX generation.", request_id)

    try:
        template_path_str = str(settings.template_path)

        # Ensure final_ctx_payload is a dictionary for _generate_and_stream_docx
        # Pydantic model ensures structure; model_dump provides the dict.
        final_context_dict = final_ctx_payload.model_dump(exclude_none=True)

        logger.info("[%s] Generating DOCX from final context...", request_id)
        docx_response = await _generate_and_stream_docx(
            template_path=template_path_str,
            final_context=final_context_dict,
            request_id=request_id,
        )
        logger.info(
            "[%s] DOCX generation successful for finalization. Returning stream.",
            request_id,
        )
        return docx_response

    except HTTPException as he:
        logger.error(
            "[%s] HTTPException during report finalization: %s - %s",
            request_id,
            he.status_code,
            he.detail,
            exc_info=True,
        )
        raise he
    except (
        DocBuilderError
    ) as e:  # Specifically for errors from _generate_and_stream_docx
        logger.error(
            "[%s] DocBuilderError during report finalization: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Report finalization document builder error: {str(e)}",
        )
    except Exception as e:
        logger.error(
            "[%s] Unexpected error during report finalization: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected server error occurred during report finalization (id: {request_id}).",
        )


# The _generate_and_stream_docx function remains as it might be used by a future /download_report endpoint
# Ensure it's defined if not already, or remove if truly no longer needed by any path.
# For this refactor, we assume it's kept for a potential separate download endpoint.
# If it was at the end of the file, it should still be there.
# ... (rest of the file, including _generate_and_stream_docx and other helpers if any)
