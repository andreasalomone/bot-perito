from __future__ import annotations

import logging

from app.core.exceptions import PipelineError  # Import from core exceptions
from app.services.llm import JSONParsingError
from app.services.llm import LLMError
from app.services.llm import execute_llm_step_with_template

# Define PipelineError or import from a central location
# from app.services.pipeline import PipelineError  # Example import

# class PipelineError(Exception):
#     """Base exception for pipeline-related errors (defined here for example)"""

logger = logging.getLogger(__name__)


class HarmonizationService:
    async def harmonize(self, request_id: str, sections: dict[str, str], reference_style_text: str) -> dict[str, str]:
        """Harmonizes the style and tone across multiple report sections."""
        logger.info("[%s] Harmonizing %d sections", request_id, len(sections))
        original_keys = set(sections.keys())

        try:
            # Remove manual string construction
            # section_joiner = "\\n\\n"  # Escaped for template rendering
            # parts = []
            # for k, v in sections.items():
            #     escaped_v = json.dumps(v)[1:-1]
            #     parts.append(f'\\"{k}": \\"\\"\\"{escaped_v}\\"\\"')
            # sections_input_for_prompt = section_joiner.join(parts)

            # Prepare context for the helper method - pass sections directly
            llm_context = {
                "sections_dict": sections,  # Pass the dictionary directly
                "reference_style_text": reference_style_text,
            }

            # Use the helper function from llm module
            harmonized_data = await execute_llm_step_with_template(
                request_id=request_id,
                step_name="harmonize",
                template_name="harmonize_prompt.jinja2",
                context=llm_context,
                expected_type=dict,  # Expecting a dict of harmonized sections
            )

            # Keep specific validation for harmonization result
            if not isinstance(harmonized_data, dict) or not original_keys.issubset(harmonized_data.keys()):
                missing_keys = original_keys - set(harmonized_data.keys())
                logger.error(
                    "[%s] Incomplete harmonization result: Missing keys. Expected: %s, Got: %s, Missing: %s",
                    request_id,
                    list(original_keys),
                    list(harmonized_data.keys()),
                    list(missing_keys),
                )
                raise PipelineError(f"Harmonization result missed expected sections: {missing_keys}")

            logger.info(
                "[%s] Successfully harmonized sections. Keys: %s",
                request_id,
                list(harmonized_data.keys()),
            )
            return harmonized_data

        except (LLMError, JSONParsingError, PipelineError) as e:
            logger.error("[%s] Harmonization failed: %s", request_id, str(e), exc_info=False)
            raise PipelineError(f"Failed to harmonize sections: {str(e)}") from e
        except Exception as e:
            # Catch unexpected errors during this specific step's orchestration
            logger.exception("[%s] Unexpected error in harmonization orchestration", request_id)
            raise PipelineError("Unexpected error during harmonization") from e
