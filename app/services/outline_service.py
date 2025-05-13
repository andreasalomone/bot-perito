from __future__ import annotations

import logging

from pydantic import ValidationError

from app.core.exceptions import PipelineError  # Import from core exceptions
from app.models.report_models import OutlineItem
from app.services.llm import JSONParsingError  # Assuming PipelineError is defined elsewhere or replaced
from app.services.llm import LLMError  # Assuming PipelineError is defined elsewhere or replaced
from app.services.llm import execute_llm_step_with_template  # Assuming PipelineError is defined elsewhere or replaced

# Define PipelineError or import from a central location
# For now, assuming it might be defined in pipeline.py or a core exceptions file
# If not, uncomment the definition below or import appropriately.
# from app.services.pipeline import PipelineError  # Example import

# class PipelineError(Exception):
#     """Base exception for pipeline-related errors (defined here for example)"""

logger = logging.getLogger(__name__)


class OutlineService:
    async def generate_outline(
        self,
        request_id: str,
        template_excerpt: str,
        corpus: str,
        notes: str,
    ) -> list[OutlineItem]:
        """Generates a structured outline (list of sections with titles and bullets)."""
        logger.info("[%s] Generating outline", request_id)

        # Input validation
        if not template_excerpt:
            logger.warning(
                "[%s] Outline generation called with empty template_excerpt.",
                request_id,
            )
            raise PipelineError("Outline generation requires a template excerpt.")
        if not corpus:
            logger.warning("[%s] Outline generation called with empty corpus.", request_id)
            raise PipelineError("Outline generation requires a corpus.")

        try:
            context = {
                "template_excerpt": template_excerpt,
                "corpus": corpus,
                "notes": notes,
            }
            # Use the helper function from llm module
            data = await execute_llm_step_with_template(
                request_id=request_id,
                step_name="generate_outline",
                template_name="generate_outline_prompt.jinja2",
                context=context,
                expected_type=list,  # Outline should be a list
            )

            # Keep specific validation for outline structure
            if not data:  # Check if the list is empty
                logger.error("[%s] Empty outline list returned from LLM", request_id)
                raise PipelineError("Empty outline generated")

            validated_outline: list[OutlineItem] = []
            for item_idx, item_data in enumerate(data):
                try:
                    validated_outline.append(OutlineItem(**item_data))
                except ValidationError as ve:
                    logger.error(
                        "[%s] Validation failed for outline item #%d: %s. Data: %s",
                        request_id,
                        item_idx,
                        ve,
                        item_data,
                    )
                    raise PipelineError(f"Invalid structure for outline item #{item_idx}: {ve}") from ve

            logger.info(
                "[%s] Successfully generated and validated outline with %d sections",
                request_id,
                len(validated_outline),
            )
            return validated_outline
        # Catch specific errors from the helper or validation
        except (LLMError, JSONParsingError, PipelineError) as e:
            logger.error(
                "[%s] Outline generation failed: %s",
                request_id,
                str(e),
                exc_info=False,  # Helper logs details
            )
            # Re-raise as PipelineError to be handled by the main orchestrator
            raise PipelineError(f"Outline generation failed: {str(e)}") from e
        except Exception as e:
            # Catch unexpected errors during this specific step's orchestration
            logger.exception("[%s] Unexpected error in generate_outline orchestration", request_id)
            raise PipelineError("Unexpected error during outline generation") from e
