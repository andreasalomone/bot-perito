import logging
from typing import Any, Dict, List

from docx import Document
from fastapi import HTTPException

from app.core.config import settings
from app.services.llm import (
    JSONParsingError,
    LLMError,
    build_prompt,
    call_llm,
    extract_json,
)
from app.services.pipeline import PipelineError

__all__ = [
    "_load_template_excerpt",
    "_extract_base_context",
]

logger = logging.getLogger(__name__)


async def _load_template_excerpt(template_path: str, request_id: str) -> str:
    """Read the first few paragraphs of the Word template to use as a style/context
    primer for the language model."""
    try:
        template_doc = Document(str(template_path))
        template_excerpt = "\n".join(p.text for p in template_doc.paragraphs[:8])
        logger.debug(
            "[%s] Loaded template excerpt: %d chars", request_id, len(template_excerpt)
        )
        return template_excerpt
    except Exception as e:
        logger.error(
            "[%s] Failed to load template for excerpt: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Error loading template excerpt.")


async def _extract_base_context(
    template_excerpt: str,
    corpus: str,
    imgs: List[str],
    notes: str,
    request_id: str,
) -> Dict[str, Any]:
    """Build the prompt and call the language model to obtain the *base* JSON context
    of the report (generic fields before the heavy pipeline)."""
    try:
        base_prompt = build_prompt(template_excerpt, corpus, imgs, notes)
        if len(base_prompt) > settings.max_total_prompt_chars:
            logger.warning(
                "[%s] Prompt too large: %d chars", request_id, len(base_prompt)
            )
            raise HTTPException(
                status_code=413, detail="Prompt too large or too many attachments"
            )

        raw_base = await call_llm(base_prompt)
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
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(
            "[%s] Unexpected error in base context extraction: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise PipelineError(f"Unexpected error during base context extraction: {e}")
