import logging
from typing import Any

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from app.core.config import settings
from app.core.exceptions import ConfigurationError
from app.core.exceptions import PipelineError
from app.services.llm import JSONParsingError
from app.services.llm import LLMError
from app.services.llm import build_prompt
from app.services.llm import call_llm
from app.services.llm import extract_json

__all__ = [
    "_load_template_excerpt",
    "_extract_base_context",
]

logger = logging.getLogger(__name__)


async def _load_template_excerpt(template_path: str, request_id: str) -> str:
    """Read the first few paragraphs of the Word template to use as a style/context
    primer for the language model.
    """
    try:
        template_doc = Document(str(template_path))
        template_excerpt = "\n".join(p.text for p in template_doc.paragraphs[:8])
        logger.debug("[%s] Loaded template excerpt: %d chars", request_id, len(template_excerpt))
        return template_excerpt
    except PackageNotFoundError as e:
        logger.error("[%s] Template file not found or corrupted: %s", request_id, template_path)
        raise ConfigurationError(f"Template file not found or invalid: {template_path}") from e
    except Exception as e:
        logger.error(
            "[%s] Failed to load template for excerpt: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise ConfigurationError("Unexpected error loading template excerpt.") from e


async def _extract_base_context(
    template_excerpt: str,
    corpus: str,
    imgs: list[str],
    notes: str,
    request_id: str,
    reference_style_text: str,
) -> dict[str, Any]:
    """Build the prompt and call the language model to obtain the *base* JSON context
    of the report (generic fields before the heavy pipeline).
    """
    try:
        base_prompt = build_prompt(template_excerpt, corpus, notes, reference_style_text)
        if len(base_prompt) > settings.max_total_prompt_chars:
            logger.warning("[%s] Prompt too large: %d chars", request_id, len(base_prompt))
            raise PipelineError("Prompt too large or too many attachments")

        raw_base = await call_llm(base_prompt)
        base_ctx = extract_json(raw_base)
        logger.info("[%s] Successfully extracted base context fields", request_id)
        return base_ctx
    except LLMError as e:
        logger.error(
            "[%s] LLM call for base context failed: %s",
            request_id,
            str(e),
            exc_info=False,
        )
        raise
    except JSONParsingError as e:
        logger.error(
            "[%s] JSON parsing for base context failed: %s",
            request_id,
            str(e),
            exc_info=False,
        )
        raise
    except Exception as e:
        logger.error(
            "[%s] Unexpected error extracting base context: %s",
            request_id,
            str(e),
            exc_info=True,
        )
        raise PipelineError("Unexpected error during base context extraction") from e
