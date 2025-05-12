from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.services.llm import (  # Assuming PipelineError is defined elsewhere or replaced
    JSONParsingError,
    LLMError,
    execute_llm_step_with_template,
)

# Define PipelineError or import from a central location
# For now, assuming it might be defined in pipeline.py or a core exceptions file
# If not, uncomment the definition below or import appropriately.
from app.services.pipeline import PipelineError  # Example import

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
    ) -> List[Dict[str, Any]]:
        """
        Generates a structured outline (list of sections with titles and bullets).
        """
        logger.info("[%s] Generating outline", request_id)
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

            logger.info(
                "[%s] Successfully generated outline with %d sections",
                request_id,
                len(data),
            )
            return data
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
            logger.exception(
                "[%s] Unexpected error in generate_outline orchestration", request_id
            )
            raise PipelineError("Unexpected error during outline generation") from e
